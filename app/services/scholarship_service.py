from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from typing import List

from app.models.scholarship import Scholarship, ScholarshipRequirement, ScholarshipStatus
from app.models.user import User
from app.schemas.scholarship import ScholarshipCreate, ScholarshipUpdate, ScholarshipStatusUpdate
from app.exceptions import NotFoundError, ValidationError


async def list_scholarships(db: AsyncSession, user: User, page: int, page_size: int):
    q = select(Scholarship)
    if user.role == "student":
        q = q.where(Scholarship.status == ScholarshipStatus.active)
    if user.role == "osfa_staff" and user.department:
        q = q.where(Scholarship.category == user.department.value)

    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_result.scalar()

    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return result.scalars().all(), total


async def get_scholarship(db: AsyncSession, scholarship_id: int) -> Scholarship:
    result = await db.execute(select(Scholarship).where(Scholarship.id == scholarship_id))
    scholarship = result.scalar_one_or_none()
    if not scholarship:
        raise NotFoundError("Scholarship", scholarship_id)
    return scholarship


async def create_scholarship(db: AsyncSession, data: ScholarshipCreate, user: User) -> Scholarship:
    if user.role == "osfa_staff" and user.department:
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
    await db.refresh(scholarship)
    return scholarship


async def update_scholarship(db: AsyncSession, scholarship_id: int, data: ScholarshipUpdate) -> Scholarship:
    scholarship = await get_scholarship(db, scholarship_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(scholarship, field, value)
    await db.commit()
    await db.refresh(scholarship)
    return scholarship


async def update_status(db: AsyncSession, scholarship_id: int, data: ScholarshipStatusUpdate) -> Scholarship:
    scholarship = await get_scholarship(db, scholarship_id)
    scholarship.status = data.status
    await db.commit()
    await db.refresh(scholarship)
    return scholarship


async def delete_scholarship(db: AsyncSession, scholarship_id: int) -> None:
    scholarship = await get_scholarship(db, scholarship_id)
    await db.delete(scholarship)
    await db.commit()


async def duplicate_scholarship(db: AsyncSession, scholarship_id: int, created_by: int) -> Scholarship:
    original = await get_scholarship(db, scholarship_id)
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
        created_by=created_by,
    )
    db.add(clone)
    await db.flush()

    reqs = await db.execute(
        select(ScholarshipRequirement).where(ScholarshipRequirement.scholarship_id == scholarship_id)
    )
    for req in reqs.scalars().all():
        db.add(ScholarshipRequirement(
            scholarship_id=clone.id,
            name=req.name,
            description=req.description,
            is_required=req.is_required,
        ))

    await db.commit()
    await db.refresh(clone)
    return clone
