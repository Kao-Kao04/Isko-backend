from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.academic_period import AcademicPeriod, GwaSubmission, GwaSubmissionStatus
from app.models.scholar import Scholar, SemesterRecord
from app.models.user import User, UserRole
from app.schemas.academic_period import AcademicPeriodCreate, GwaSubmissionReview, GwaSubmissionReject
from app.exceptions import NotFoundError, ValidationError, ForbiddenError


# ── Academic Period management (super admin) ──────────────────────────────────

async def get_current_period(db: AsyncSession) -> AcademicPeriod | None:
    result = await db.execute(select(AcademicPeriod))
    periods = result.scalars().all()
    for p in periods:
        if p.is_active:
            return p
    return None


async def list_periods(db: AsyncSession) -> list[AcademicPeriod]:
    result = await db.execute(select(AcademicPeriod).order_by(AcademicPeriod.start_date.desc()))
    return list(result.scalars().all())


async def create_period(db: AsyncSession, data: AcademicPeriodCreate, actor: User) -> AcademicPeriod:
    if actor.role != UserRole.super_admin:
        raise ForbiddenError("Super admin access required")
    period = AcademicPeriod(**data.model_dump())
    db.add(period)
    await db.commit()
    await db.refresh(period)
    return period


async def delete_period(db: AsyncSession, period_id: int, actor: User) -> None:
    if actor.role != UserRole.super_admin:
        raise ForbiddenError("Super admin access required")
    result = await db.execute(
        select(AcademicPeriod)
        .options(selectinload(AcademicPeriod.gwa_submissions))
        .where(AcademicPeriod.id == period_id)
    )
    period = result.scalar_one_or_none()
    if not period:
        raise NotFoundError("AcademicPeriod", period_id)
    if period.gwa_submissions:
        raise ValidationError("Cannot delete a period that has GWA submissions. Archive it instead.")
    await db.delete(period)
    await db.commit()


# ── GWA Submission (student → OSFA) ──────────────────────────────────────────

async def _get_scholar_for_student(db: AsyncSession, scholar_id: int, student_id: int) -> Scholar:
    result = await db.execute(
        select(Scholar)
        .options(selectinload(Scholar.scholarship))
        .where(Scholar.id == scholar_id, Scholar.student_id == student_id)
    )
    scholar = result.scalar_one_or_none()
    if not scholar:
        raise NotFoundError("Scholar", scholar_id)
    return scholar


async def submit_gwa(
    db: AsyncSession,
    scholar_id: int,
    period_id: int,
    declared_gwa: str | None,
    has_grade_below_2_5: bool,
    proof_path: str,
    student: User,
) -> GwaSubmission:
    scholar = await _get_scholar_for_student(db, scholar_id, student.id)

    result = await db.execute(select(AcademicPeriod).where(AcademicPeriod.id == period_id))
    period = result.scalar_one_or_none()
    if not period:
        raise NotFoundError("AcademicPeriod", period_id)
    if not period.is_ended:
        raise ValidationError(
            "GWA submission is only allowed after the semester has ended. "
            "Please wait until the semester period is over before submitting your grades."
        )

    # Validate GWA format if provided (PUP scale: 1.00 - 5.00)
    if declared_gwa is not None:
        try:
            gwa_float = float(declared_gwa)
            if not (1.0 <= gwa_float <= 5.0):
                raise ValidationError("GWA must be between 1.00 and 5.00 (PUP grading scale)")
            declared_gwa = f"{gwa_float:.2f}"
        except (ValueError, TypeError):
            raise ValidationError("GWA must be a valid number (e.g. 1.75)")

    # Check for existing submission
    existing = await db.execute(
        select(GwaSubmission).where(
            GwaSubmission.scholar_id == scholar_id,
            GwaSubmission.period_id == period_id,
        )
    )
    sub = existing.scalar_one_or_none()

    if sub:
        if sub.status == GwaSubmissionStatus.approved:
            raise ValidationError("Your GWA for this period has already been approved.")
        if sub.status == GwaSubmissionStatus.pending:
            raise ValidationError(
                "You already have a pending GWA submission for this period. "
                "Please wait for OSFA to review it."
            )
        # Rejected — allow resubmit: update in place
        from app.utils.storage import delete_file
        await delete_file(sub.proof_path)
        sub.declared_gwa = declared_gwa
        sub.has_grade_below_2_5 = has_grade_below_2_5
        sub.proof_path = proof_path
        sub.status = GwaSubmissionStatus.pending
        sub.rejection_remarks = None
        sub.submitted_at = datetime.now(timezone.utc)
        sub.reviewed_at = None
        sub.reviewed_by_id = None
        await db.commit()
        await db.refresh(sub)
        return sub

    sub = GwaSubmission(
        scholar_id=scholar_id,
        period_id=period_id,
        declared_gwa=declared_gwa,
        has_grade_below_2_5=has_grade_below_2_5,
        proof_path=proof_path,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


async def list_gwa_submissions(
    db: AsyncSession,
    scholar_id: int,
    actor: User,
) -> list[GwaSubmission]:
    if actor.role == UserRole.student:
        result = await db.execute(
            select(Scholar).where(Scholar.id == scholar_id, Scholar.student_id == actor.id)
        )
        if not result.scalar_one_or_none():
            raise ForbiddenError()
    result = await db.execute(
        select(GwaSubmission)
        .options(selectinload(GwaSubmission.period))
        .where(GwaSubmission.scholar_id == scholar_id)
        .order_by(GwaSubmission.submitted_at.desc())
    )
    return list(result.scalars().all())


async def list_pending_gwa_submissions(db: AsyncSession, actor: User) -> list[GwaSubmission]:
    """All pending submissions — optionally filtered by OSFA staff dept."""
    from app.models.scholarship import Scholarship
    q = (
        select(GwaSubmission)
        .options(
            selectinload(GwaSubmission.period),
            selectinload(GwaSubmission.scholar).selectinload(Scholar.scholarship),
        )
        .join(Scholar, Scholar.id == GwaSubmission.scholar_id)
        .where(GwaSubmission.status == GwaSubmissionStatus.pending)
        .order_by(GwaSubmission.submitted_at.asc())
    )
    if actor.role == UserRole.osfa_staff and actor.department:
        q = q.join(Scholarship, Scholarship.id == Scholar.scholarship_id).where(
            Scholarship.category == actor.department.value
        )
    result = await db.execute(q)
    return list(result.scalars().all())


async def _get_submission(db: AsyncSession, scholar_id: int, sub_id: int) -> GwaSubmission:
    result = await db.execute(
        select(GwaSubmission)
        .options(selectinload(GwaSubmission.period))
        .where(GwaSubmission.id == sub_id, GwaSubmission.scholar_id == scholar_id)
    )
    sub = result.scalar_one_or_none()
    if not sub:
        raise NotFoundError("GwaSubmission", sub_id)
    return sub


async def approve_gwa_submission(
    db: AsyncSession,
    scholar_id: int,
    sub_id: int,
    data: GwaSubmissionReview,
    actor: User,
) -> GwaSubmission:
    sub = await _get_submission(db, scholar_id, sub_id)
    if sub.status != GwaSubmissionStatus.pending:
        raise ValidationError(f"Submission is already '{sub.status}' and cannot be approved again.")

    result = await db.execute(
        select(Scholar)
        .options(selectinload(Scholar.scholarship))
        .where(Scholar.id == scholar_id)
    )
    scholar = result.scalar_one_or_none()
    if not scholar:
        raise NotFoundError("Scholar", scholar_id)

    confirmed_gwa = data.confirmed_gwa if data.confirmed_gwa is not None else sub.declared_gwa
    if confirmed_gwa is not None:
        try:
            gwa_float = float(confirmed_gwa)
            if not (1.0 <= gwa_float <= 5.0):
                raise ValidationError("GWA must be between 1.00 and 5.00")
            confirmed_gwa = f"{gwa_float:.2f}"
        except (ValueError, TypeError):
            raise ValidationError("GWA must be a valid number")

    has_below = data.has_grade_below_2_5 if data.has_grade_below_2_5 is not None else sub.has_grade_below_2_5

    sub.status = GwaSubmissionStatus.approved
    sub.reviewed_at = datetime.now(timezone.utc)
    sub.reviewed_by_id = actor.id
    sub.declared_gwa = confirmed_gwa  # overwrite with OSFA-confirmed value
    sub.has_grade_below_2_5 = has_below

    # Create SemesterRecord from the approved submission
    period = sub.period
    sem_label = {"first": "1st Semester", "second": "2nd Semester", "summer": "Summer"}
    semester_str = sem_label.get(period.semester.value if hasattr(period.semester, 'value') else period.semester, str(period.semester))

    # Check if a record already exists for this scholar + period
    existing_record = (await db.execute(
        select(SemesterRecord).where(
            SemesterRecord.scholar_id == scholar_id,
            SemesterRecord.academic_year == period.academic_year,
            SemesterRecord.semester == semester_str,
        )
    )).scalar_one_or_none()

    if existing_record:
        existing_record.gwa = confirmed_gwa
        existing_record.has_grade_below_2_5 = has_below
        if data.notes:
            existing_record.notes = data.notes
    else:
        record = SemesterRecord(
            scholar_id=scholar_id,
            semester=semester_str,
            academic_year=period.academic_year,
            gwa=confirmed_gwa,
            has_grade_below_2_5=has_below,
            is_enrolled=True,
            notes=data.notes,
        )
        db.add(record)
        await db.flush()
        # Auto-evaluate scholar status based on new GWA
        from app.services.scholar_service import _evaluate_retention
        await _evaluate_retention(db, scholar, confirmed_gwa, has_below)

    # Cache ORM attribute values before commit — after commit all objects are expired
    # and accessing them in async context raises MissingGreenlet.
    _student_id   = int(scholar.student_id)        # type: ignore[arg-type]
    _app_id       = int(scholar.application_id) if scholar.application_id else None  # type: ignore[arg-type]
    _sch_name     = str(scholar.scholarship.name) if scholar.scholarship else "your scholarship"
    _period_label = period.label
    _gwa_part     = f" Confirmed GWA: {confirmed_gwa}." if confirmed_gwa else ""

    await db.commit()
    await db.refresh(sub)

    try:
        from app.services.notification_service import create_notification
        await create_notification(
            db, _student_id,
            "GWA Submission Approved",
            f"OSFA has verified your grade submission for {_period_label} ({_sch_name}).{_gwa_part}",
            _app_id,
        )
        await db.commit()
    except Exception:
        pass

    return sub


async def reject_gwa_submission(
    db: AsyncSession,
    scholar_id: int,
    sub_id: int,
    data: GwaSubmissionReject,
    actor: User,
) -> GwaSubmission:
    sub = await _get_submission(db, scholar_id, sub_id)
    if sub.status != GwaSubmissionStatus.pending:
        raise ValidationError(f"Submission is already '{sub.status}' and cannot be rejected.")

    result = await db.execute(
        select(Scholar)
        .options(selectinload(Scholar.scholarship))
        .where(Scholar.id == scholar_id)
    )
    scholar = result.scalar_one_or_none()
    if not scholar:
        raise NotFoundError("Scholar", scholar_id)

    # Cache ORM attribute values before commit — after commit all objects are expired
    # and accessing them in async context raises MissingGreenlet.
    _student_id   = int(scholar.student_id)        # type: ignore[arg-type]
    _app_id       = int(scholar.application_id) if scholar.application_id else None  # type: ignore[arg-type]
    _sch_name     = str(scholar.scholarship.name) if scholar.scholarship else "your scholarship"
    _period_label = sub.period.label

    sub.status = GwaSubmissionStatus.rejected
    sub.rejection_remarks = data.remarks
    sub.reviewed_at = datetime.now(timezone.utc)
    sub.reviewed_by_id = actor.id
    await db.commit()
    await db.refresh(sub)

    try:
        from app.services.notification_service import create_notification
        await create_notification(
            db, _student_id,
            "GWA Submission Rejected",
            f"Your grade submission for {_period_label} ({_sch_name}) was rejected. "
            f"Reason: {data.remarks}. Please resubmit with the correct documents.",
            _app_id,
        )
        await db.commit()
    except Exception:
        pass

    return sub
