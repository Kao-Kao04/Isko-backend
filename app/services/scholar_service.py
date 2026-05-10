from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.scholar import Scholar, ScholarStatus, SemesterRecord, ScholarStatusLog, SCHOLAR_STATUS_TRANSITIONS
from app.models.user import User
from app.schemas.scholar import ScholarStatusUpdate, SemesterRecordCreate, SemesterRecordUpdate
from app.exceptions import NotFoundError, ValidationError


async def get_scholars_by_student(db: AsyncSession, student_id: int) -> list[Scholar]:
    result = await db.execute(select(Scholar).where(Scholar.student_id == student_id))
    return list(result.scalars().all())


async def list_scholars(db: AsyncSession, page: int, page_size: int):
    q = select(Scholar)
    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_result.scalar()
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return result.scalars().all(), total


async def get_scholar(db: AsyncSession, scholar_id: int) -> Scholar:
    result = await db.execute(select(Scholar).where(Scholar.id == scholar_id))
    scholar = result.scalar_one_or_none()
    if not scholar:
        raise NotFoundError("Scholar", scholar_id)
    return scholar


async def update_scholar_status(
    db: AsyncSession,
    scholar_id: int,
    data: ScholarStatusUpdate,
    actor: User | None = None,
) -> Scholar:
    scholar = await get_scholar(db, scholar_id)
    old_status = scholar.status

    allowed = SCHOLAR_STATUS_TRANSITIONS.get(old_status, [])
    if data.status not in allowed:
        raise ValidationError(
            f"Cannot transition scholar from '{old_status}' to '{data.status}'. "
            f"Allowed: {[s.value for s in allowed] or 'none (terminal state)'}"
        )

    scholar.status = data.status
    if data.is_graduating is not None:
        scholar.is_graduating = data.is_graduating
    if data.expected_graduation is not None:
        scholar.expected_graduation = data.expected_graduation

    log = ScholarStatusLog(
        scholar_id=scholar_id,
        from_status=old_status,
        to_status=data.status,
        actor_id=actor.id if actor else None,
        reason=data.reason,
    )
    db.add(log)

    if data.status.value == "terminated":
        from app.utils.email import send_scholar_terminated_email
        from app.models.user import User as UserModel
        from sqlalchemy.orm import selectinload as _sel
        result = await db.execute(
            select(UserModel).where(UserModel.id == scholar.student_id)
        )
        user = result.scalar_one_or_none()
        if user:
            try:
                await send_scholar_terminated_email(user.email, data.reason)
            except Exception:
                pass  # email failure must not block the status update

    await db.commit()
    await db.refresh(scholar)
    return scholar


async def _evaluate_retention(db: AsyncSession, scholar: Scholar, gwa: str | None, has_grade_below_2_5: bool) -> None:
    """Auto-set scholar status based on GWA and grade flag after a semester record is saved."""
    from app.models.scholarship import Scholarship
    sch_result = await db.execute(select(Scholarship).where(Scholarship.id == scholar.scholarship_id))
    scholarship = sch_result.scalar_one_or_none()
    min_gwa = float(scholarship.min_gwa) if (scholarship and scholarship.min_gwa) else 2.0

    if not gwa:
        return  # no GWA submitted yet — nothing to evaluate

    try:
        student_gwa = float(gwa)
    except (ValueError, TypeError):
        return

    # In PUP grading: lower number = better. 1.0 is best, 5.0 is failing.
    gwa_fails = student_gwa > min_gwa
    grade_flag_fails = has_grade_below_2_5

    current = scholar.status
    if current in (ScholarStatus.terminated, ScholarStatus.graduated):
        return  # terminal — never auto-change

    if gwa_fails or grade_flag_fails:
        if current == ScholarStatus.active:
            allowed = SCHOLAR_STATUS_TRANSITIONS.get(current, [])
            if ScholarStatus.probationary in allowed:
                reason = []
                if gwa_fails:
                    reason.append(f"GWA {gwa} is below required {min_gwa}")
                if grade_flag_fails:
                    reason.append("has subject grade below 2.5")
                log = ScholarStatusLog(
                    scholar_id=scholar.id,
                    from_status=current,
                    to_status=ScholarStatus.probationary,
                    actor_id=None,
                    reason="Auto-evaluated: " + "; ".join(reason),
                )
                db.add(log)
                scholar.status = ScholarStatus.probationary
    else:
        # GWA and grades are good — lift probation if currently on it
        if current == ScholarStatus.probationary:
            log = ScholarStatusLog(
                scholar_id=scholar.id,
                from_status=current,
                to_status=ScholarStatus.active,
                actor_id=None,
                reason=f"Auto-evaluated: GWA {gwa} meets requirement; no failing grades",
            )
            db.add(log)
            scholar.status = ScholarStatus.active


async def add_semester_record(db: AsyncSession, scholar_id: int, data: SemesterRecordCreate) -> SemesterRecord:
    scholar = await get_scholar(db, scholar_id)
    record = SemesterRecord(scholar_id=scholar_id, **data.model_dump())
    db.add(record)
    await db.flush()
    await _evaluate_retention(db, scholar, data.gwa, data.has_grade_below_2_5)
    await db.commit()
    await db.refresh(record)
    return record


async def update_semester_record(
    db: AsyncSession, scholar_id: int, record_id: int, data: SemesterRecordUpdate
) -> SemesterRecord:
    result = await db.execute(
        select(SemesterRecord).where(SemesterRecord.id == record_id, SemesterRecord.scholar_id == scholar_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise NotFoundError("SemesterRecord", record_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    # Re-evaluate retention whenever GWA or grade flag changes
    if data.gwa is not None or data.has_grade_below_2_5 is not None:
        scholar = await get_scholar(db, scholar_id)
        await _evaluate_retention(
            db, scholar,
            record.gwa,
            record.has_grade_below_2_5,
        )
    await db.commit()
    await db.refresh(record)
    return record
