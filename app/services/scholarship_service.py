from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from app.models.scholarship import Scholarship, ScholarshipRequirement, ScholarshipStatus
from app.models.application import Application, ApplicationStatus
from app.models.user import User, UserRole
from app.schemas.scholarship import ScholarshipCreate, ScholarshipUpdate, ScholarshipStatusUpdate
from app.exceptions import NotFoundError, ForbiddenError, ValidationError

# Allowed scholarship status transitions — prevents arbitrary jumps
_STATUS_TRANSITIONS: dict[ScholarshipStatus, list[ScholarshipStatus]] = {
    ScholarshipStatus.draft:     [ScholarshipStatus.active, ScholarshipStatus.archived],
    ScholarshipStatus.active:    [ScholarshipStatus.closed],
    ScholarshipStatus.closed:    [ScholarshipStatus.archived, ScholarshipStatus.active],
    ScholarshipStatus.archived:  [],  # terminal
}


def _check_dept_owns_scholarship(scholarship: Scholarship, staff: User) -> None:
    """OSFA staff can only modify scholarships within their department."""
    if staff.role == UserRole.osfa_staff and staff.department and scholarship.category != staff.department:
        raise ForbiddenError("This scholarship belongs to a different department")


def _with_requirements(q):
    return q.options(selectinload(Scholarship.requirements))


async def _attach_applicants_counts(db: AsyncSession, scholarships: list) -> None:
    if not scholarships:
        return
    ids = [s.id for s in scholarships]
    rows = await db.execute(
        select(Application.scholarship_id, func.count(Application.id))
        .where(
            Application.scholarship_id.in_(ids),
            Application.status.notin_([ApplicationStatus.withdrawn]),
        )
        .group_by(Application.scholarship_id)
    )
    counts = {row[0]: row[1] for row in rows}
    for s in scholarships:
        s.applicants_count = counts.get(s.id, 0)


async def list_scholarships(db: AsyncSession, user: User, page: int, page_size: int):
    base = select(Scholarship)
    if user.role == UserRole.student:
        base = base.where(Scholarship.status == ScholarshipStatus.active)
    elif user.role == UserRole.osfa_staff and user.department:
        base = base.where(Scholarship.category == user.department.value)

    base = base.order_by(Scholarship.created_at.desc())
    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar()

    q = _with_requirements(base).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    scholarships = list(result.scalars().all())
    await _attach_applicants_counts(db, scholarships)
    return scholarships, total


async def get_scholarship(db: AsyncSession, scholarship_id: int, user: User | None = None) -> Scholarship:
    result = await db.execute(
        _with_requirements(select(Scholarship).where(Scholarship.id == scholarship_id))
    )
    scholarship = result.scalar_one_or_none()
    if not scholarship:
        raise NotFoundError("Scholarship", scholarship_id)
    # Students cannot view draft or archived scholarships
    if user and user.role == UserRole.student:
        if scholarship.status not in (ScholarshipStatus.active, ScholarshipStatus.closed):
            raise NotFoundError("Scholarship", scholarship_id)
    await _attach_applicants_counts(db, [scholarship])
    return scholarship


async def create_scholarship(db: AsyncSession, data: ScholarshipCreate, user: User) -> Scholarship:
    # OSFA staff always create within their department; super_admin can specify freely
    if user.role == UserRole.osfa_staff and user.department:
        data.category = user.department.value
    if not data.category:
        data.category = "public"

    scholarship = Scholarship(
        name=data.name,
        description=data.description,
        slots=data.slots,
        deadline=data.deadline,
        eligible_colleges=data.eligible_colleges,
        eligible_programs=data.eligible_programs,
        eligible_year_levels=data.eligible_year_levels,
        min_gwa=data.min_gwa,
        category=data.category,
        created_by=user.id,
    )
    db.add(scholarship)
    await db.flush()

    for req in data.requirements:
        r = ScholarshipRequirement(
            scholarship_id=scholarship.id,
            name=req.name,
            description=req.description,
            is_required=req.is_required,
        )
        db.add(r)

    await db.commit()
    return await get_scholarship(db, scholarship.id)


async def update_scholarship(db: AsyncSession, scholarship_id: int, data: ScholarshipUpdate, user: User) -> Scholarship:
    scholarship = await get_scholarship(db, scholarship_id)
    _check_dept_owns_scholarship(scholarship, user)

    update_data = data.model_dump(exclude_unset=True)
    requirements_data = update_data.pop('requirements', None)
    for field, value in update_data.items():
        setattr(scholarship, field, value)
    if requirements_data is not None:
        for req in scholarship.requirements:
            await db.delete(req)
        for req in requirements_data:
            db.add(ScholarshipRequirement(
                scholarship_id=scholarship_id,
                name=req['name'],
                description=req.get('description'),
                is_required=req.get('is_required', True),
            ))
    await db.commit()
    return await get_scholarship(db, scholarship_id)


async def update_status(db: AsyncSession, scholarship_id: int, data: ScholarshipStatusUpdate, user: User) -> Scholarship:
    scholarship = await get_scholarship(db, scholarship_id)
    _check_dept_owns_scholarship(scholarship, user)

    allowed = _STATUS_TRANSITIONS.get(scholarship.status, [])
    if data.status not in allowed:
        raise ValidationError(
            f"Cannot transition scholarship status from '{scholarship.status}' to '{data.status}'. "
            f"Allowed: {[s.value for s in allowed] or 'none (terminal state)'}"
        )

    scholarship.status = data.status
    await db.commit()
    return await get_scholarship(db, scholarship_id)


async def delete_scholarship(db: AsyncSession, scholarship_id: int, user: User) -> None:
    result = await db.execute(
        select(Scholarship)
        .options(selectinload(Scholarship.requirements))
        .where(Scholarship.id == scholarship_id)
    )
    scholarship = result.scalar_one_or_none()
    if not scholarship:
        raise NotFoundError("Scholarship", scholarship_id)

    _check_dept_owns_scholarship(scholarship, user)

    # Prevent deletion if any non-withdrawn applications exist
    app_count_result = await db.execute(
        select(func.count(Application.id)).where(
            Application.scholarship_id == scholarship_id,
            Application.status.notin_([ApplicationStatus.withdrawn]),
        )
    )
    active_app_count = app_count_result.scalar()
    if active_app_count > 0:
        raise ValidationError(
            f"Cannot delete this scholarship — it has {active_app_count} active application(s). "
            "Archive it instead, or withdraw all applications first."
        )

    await db.delete(scholarship)
    await db.commit()


async def duplicate_scholarship(db: AsyncSession, scholarship_id: int, user: User) -> Scholarship:
    original = await get_scholarship(db, scholarship_id)
    _check_dept_owns_scholarship(original, user)

    clone = Scholarship(
        name=f"{original.name} (Copy)",
        description=original.description,
        slots=original.slots,
        deadline=original.deadline,
        eligible_colleges=original.eligible_colleges,
        eligible_programs=original.eligible_programs,
        eligible_year_levels=original.eligible_year_levels,
        min_gwa=original.min_gwa,
        category=original.category,
        status=ScholarshipStatus.draft,
        created_by=user.id,
    )
    db.add(clone)
    await db.flush()

    for req in original.requirements:
        db.add(ScholarshipRequirement(
            scholarship_id=clone.id,
            name=req.name,
            description=req.description,
            is_required=req.is_required,
        ))

    await db.commit()
    return await get_scholarship(db, clone.id)
