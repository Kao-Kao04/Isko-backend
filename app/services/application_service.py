from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from app.models.application import Application, ApplicationStatus, WorkflowLog
from app.models.scholarship import Scholarship, ScholarshipStatus
from app.models.scholar import Scholar
from app.models.appeal import Appeal, AppealStatus
from app.models.user import User, UserRole
from app.models.workflow import MainStatus, SubStatus
from app.schemas.application import (
    ApplicationCreate, ApplicationStatusUpdate, EvalStatusUpdate, EvalScoreUpdate,
    AppealCreate, AppealReview,
)
from app.services.notification_service import create_notification
from app.utils.audit import append_audit
from app.exceptions import NotFoundError, ForbiddenError, ValidationError, ConflictError


def _with_relations(q):
    return q.options(
        selectinload(Application.appeal),
        selectinload(Application.scholarship),
        selectinload(Application.student).selectinload(User.student_profile),
        selectinload(Application.scholar),
    )


async def _get_application(db: AsyncSession, application_id: int) -> Application:
    result = await db.execute(
        _with_relations(select(Application).where(Application.id == application_id))
    )
    app = result.scalar_one_or_none()
    if not app:
        raise NotFoundError("Application", application_id)
    return app


def _check_eligibility(scholarship: Scholarship, student_profile) -> None:
    if scholarship.eligible_colleges and student_profile.college not in scholarship.eligible_colleges:
        raise ValidationError("Not eligible: college restriction")
    if scholarship.eligible_programs and student_profile.program not in scholarship.eligible_programs:
        raise ValidationError("Not eligible: program restriction")
    if scholarship.eligible_year_levels and student_profile.year_level not in scholarship.eligible_year_levels:
        raise ValidationError("Not eligible: year level restriction")
    # GWA check — lower is better in the Philippine grading system
    if scholarship.min_gwa and student_profile.gwa:
        try:
            student_gwa = float(student_profile.gwa)
            required_gwa = float(scholarship.min_gwa)
            if student_gwa > required_gwa:
                raise ValidationError(
                    f"Not eligible: GWA of {student_profile.gwa} does not meet the minimum requirement of {scholarship.min_gwa}"
                )
        except (ValueError, TypeError):
            pass  # Unparseable GWA — skip the check rather than blocking the student


async def list_applications(db: AsyncSession, user: User, page: int, page_size: int, status: str | None = None):
    q = select(Application)
    if user.role == UserRole.student:
        q = q.where(Application.student_id == user.id)
    if user.role == UserRole.osfa_staff and user.department:
        q = (q
            .join(Scholarship, Application.scholarship_id == Scholarship.id)
            .where(Scholarship.category == user.department.value))
    if status:
        try:
            q = q.where(Application.status == ApplicationStatus(status))
        except ValueError:
            pass

    q = q.order_by(Application.submitted_at.desc())
    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_result.scalar()
    q = _with_relations(q).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return result.scalars().all(), total


async def count_applications(db: AsyncSession, user: User, status: str | None = None) -> int:
    """Efficient COUNT-only query — use this instead of list_applications for counts."""
    q = select(func.count(Application.id))
    if user.role == UserRole.student:
        q = q.where(Application.student_id == user.id)
    if user.role == UserRole.osfa_staff and user.department:
        q = (q
            .join(Scholarship, Application.scholarship_id == Scholarship.id)
            .where(Scholarship.category == user.department.value))
    if status:
        try:
            q = q.where(Application.status == ApplicationStatus(status))
        except ValueError:
            pass
    result = await db.execute(q)
    return result.scalar()


async def get_application(db: AsyncSession, application_id: int, user: User) -> Application:
    app = await _get_application(db, application_id)
    if user.role == UserRole.student and app.student_id != user.id:
        raise ForbiddenError()
    return app


async def submit_application(db: AsyncSession, data: ApplicationCreate, student: User) -> Application:
    sch_result = await db.execute(select(Scholarship).where(Scholarship.id == data.scholarship_id))
    scholarship = sch_result.scalar_one_or_none()
    if not scholarship:
        raise NotFoundError("Scholarship", data.scholarship_id)
    if scholarship.status != ScholarshipStatus.active:
        raise ValidationError("Scholarship is not accepting applications")

    # Deadline enforcement
    if scholarship.deadline and scholarship.deadline < datetime.now(timezone.utc):
        raise ValidationError("The application deadline for this scholarship has passed")

    # Eligibility check — profile must exist for a verified student
    if not student.student_profile:
        raise ValidationError("Your student profile is incomplete. Please complete registration before applying.")
    _check_eligibility(scholarship, student.student_profile)

    # Slot enforcement — lock scholarship row to prevent race condition
    if scholarship.slots is not None:
        locked = await db.execute(
            select(Scholarship).where(Scholarship.id == data.scholarship_id).with_for_update()
        )
        locked_sch = locked.scalar_one_or_none()
        if locked_sch and locked_sch.slots is not None:
            slot_count = await db.execute(
                select(func.count(Application.id)).where(
                    Application.scholarship_id == data.scholarship_id,
                    Application.status.notin_([ApplicationStatus.withdrawn]),
                )
            )
            if slot_count.scalar() >= locked_sch.slots:
                raise ValidationError("This scholarship has no available slots")

    existing = await db.execute(
        select(Application).where(
            Application.student_id == student.id,
            Application.scholarship_id == data.scholarship_id,
            Application.status.notin_([ApplicationStatus.withdrawn]),
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError("Already applied to this scholarship")

    from sqlalchemy.exc import IntegrityError
    app = Application(student_id=student.id, scholarship_id=data.scholarship_id)
    db.add(app)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ConflictError("Already applied to this scholarship")

    # Auto-initialize workflow on submission
    log = WorkflowLog(
        application_id=app.id,
        changed_by=student.id,
        from_main=None,
        from_sub=None,
        to_main=MainStatus.APPLICATION,
        to_sub=SubStatus.SUBMITTED,
    )
    db.add(log)
    app.main_status = MainStatus.APPLICATION
    app.sub_status = SubStatus.SUBMITTED

    await append_audit(db, app.id, student.id, "submitted", to_status=ApplicationStatus.pending)
    await create_notification(
        db, student.id, "Application Submitted",
        f"Your application for {scholarship.name} has been submitted.", app.id
    )
    await db.commit()
    return await _get_application(db, app.id)


async def resubmit_application(db: AsyncSession, application_id: int, student: User) -> Application:
    app = await _get_application(db, application_id)
    if app.student_id != student.id:
        raise ForbiddenError()
    if app.status != ApplicationStatus.incomplete:
        raise ValidationError("Can only resubmit Incomplete applications")

    old_status = app.status
    app.status = ApplicationStatus.pending

    # Sync workflow: REVISION_REQUESTED → PENDING_VALIDATION
    if (app.main_status == MainStatus.VERIFICATION
            and app.sub_status == SubStatus.REVISION_REQUESTED):
        log = WorkflowLog(
            application_id=app.id,
            changed_by=student.id,
            from_main=app.main_status,
            from_sub=app.sub_status,
            to_main=MainStatus.VERIFICATION,
            to_sub=SubStatus.PENDING_VALIDATION,
        )
        db.add(log)
        app.main_status = MainStatus.VERIFICATION
        app.sub_status = SubStatus.PENDING_VALIDATION

    await append_audit(db, app.id, student.id, "resubmitted", from_status=old_status, to_status=ApplicationStatus.pending)

    sch_result = await db.execute(select(Scholarship).where(Scholarship.id == app.scholarship_id))
    scholarship = sch_result.scalar_one_or_none()
    await create_notification(
        db, student.id, "Application Resubmitted",
        f"Your application for {scholarship.name if scholarship else 'the scholarship'} has been resubmitted.", app.id
    )
    await db.commit()
    return await _get_application(db, app.id)


async def withdraw_application(db: AsyncSession, application_id: int, student: User) -> None:
    app = await _get_application(db, application_id)
    if app.student_id != student.id:
        raise ForbiddenError()
    if app.status not in (ApplicationStatus.pending, ApplicationStatus.incomplete):
        raise ValidationError("Can only withdraw Pending or Incomplete applications")

    old_status = app.status
    app.status = ApplicationStatus.withdrawn

    # Sync workflow state if initialized and not terminal
    from app.models.workflow import is_terminal
    if app.main_status is not None and not is_terminal(app.main_status, app.sub_status):
        log = WorkflowLog(
            application_id=app.id,
            changed_by=student.id,
            from_main=app.main_status,
            from_sub=app.sub_status,
            to_main=MainStatus.WITHDRAWN,
            to_sub=SubStatus.WITHDRAWN,
        )
        db.add(log)
        app.main_status = MainStatus.WITHDRAWN
        app.sub_status = SubStatus.WITHDRAWN
        app.closed_at = datetime.now(timezone.utc)

    await append_audit(db, app.id, student.id, "withdrawn", from_status=old_status, to_status=ApplicationStatus.withdrawn)
    await db.commit()


def _check_department_ownership(app: Application, staff: User) -> None:
    """Ensure OSFA staff only act on scholarships within their department."""
    if staff.department and app.scholarship and app.scholarship.category != staff.department:
        raise ForbiddenError("This scholarship belongs to a different department")


async def update_application_status(
    db: AsyncSession, application_id: int, data: ApplicationStatusUpdate, staff: User
) -> Application:
    app = await _get_application(db, application_id)
    _check_department_ownership(app, staff)
    old_status = app.status

    allowed_transitions = {
        ApplicationStatus.pending: [ApplicationStatus.approved, ApplicationStatus.rejected, ApplicationStatus.incomplete],
        ApplicationStatus.incomplete: [ApplicationStatus.approved, ApplicationStatus.rejected],
    }
    if data.status not in allowed_transitions.get(old_status, []):
        raise ValidationError(f"Cannot transition from {old_status} to {data.status}")

    app.status = data.status
    if data.remarks:
        app.remarks = data.remarks
    if data.rejected_docs is not None:
        app.rejected_docs = data.rejected_docs

    await append_audit(db, app.id, staff.id, f"status_changed_to_{data.status}", from_status=old_status, to_status=data.status, note=data.remarks)

    sch_result = await db.execute(select(Scholarship).where(Scholarship.id == app.scholarship_id))
    scholarship = sch_result.scalar_one_or_none()
    sch_name = scholarship.name if scholarship else "the scholarship"

    notif_map = {
        ApplicationStatus.approved: ("Application Approved", f"Congratulations! Your application for {sch_name} has been approved."),
        ApplicationStatus.rejected: ("Application Rejected", f"Your application for {sch_name} has been rejected."),
        ApplicationStatus.incomplete: ("Application Incomplete", f"Your application for {sch_name} requires additional documents."),
    }
    title, body = notif_map[data.status]
    await create_notification(db, app.student_id, title, body, app.id)

    # Send email for rejection and incomplete — critical events the student may miss in-app
    if data.status in (ApplicationStatus.rejected, ApplicationStatus.incomplete):
        from app.models.user import User as _User
        user_result = await db.execute(select(_User).where(_User.id == app.student_id))
        user = user_result.scalar_one_or_none()
        if user:
            from app.utils.email import send_application_status_email
            try:
                await send_application_status_email(user.email, sch_name, data.status.value, data.remarks)
            except Exception:
                pass  # email failure must not block the status update

    if data.status == ApplicationStatus.approved:
        from sqlalchemy.exc import IntegrityError
        existing = await db.execute(select(Scholar).where(Scholar.application_id == app.id))
        if not existing.scalar_one_or_none():
            scholar = Scholar(
                application_id=app.id,
                student_id=app.student_id,
                scholarship_id=app.scholarship_id,
            )
            db.add(scholar)
            # Use a savepoint so an IntegrityError only rolls back the Scholar
            # insert, NOT the status update already pending in the outer transaction.
            async with db.begin_nested():
                try:
                    await db.flush()
                except IntegrityError:
                    pass  # Scholar already exists — harmless duplicate, outer tx intact

    await db.commit()
    return await _get_application(db, app.id)


async def update_eval_status(
    db: AsyncSession, application_id: int, data: EvalStatusUpdate, staff: User
) -> Application:
    app = await _get_application(db, application_id)
    _check_department_ownership(app, staff)
    app.eval_status = data.eval_status
    await db.commit()
    return await _get_application(db, app.id)


async def update_eval_score(
    db: AsyncSession, application_id: int, data: EvalScoreUpdate, staff: User
) -> Application:
    app = await _get_application(db, application_id)
    _check_department_ownership(app, staff)
    app.eval_score = data.model_dump()
    await db.commit()
    return await _get_application(db, app.id)


async def file_appeal(db: AsyncSession, application_id: int, data: AppealCreate, student: User) -> Appeal:
    app = await _get_application(db, application_id)
    if app.student_id != student.id:
        raise ForbiddenError()

    # Support appeal for both legacy rejection and workflow decision rejection
    is_legacy_rejected = app.status == ApplicationStatus.rejected
    is_workflow_rejected = (
        app.main_status == MainStatus.DECISION
        and app.sub_status == SubStatus.REJECTED
    )
    if not is_legacy_rejected and not is_workflow_rejected:
        raise ValidationError("Can only appeal Rejected applications")

    existing = await db.execute(select(Appeal).where(Appeal.application_id == application_id))
    if existing.scalar_one_or_none():
        raise ConflictError("Appeal already filed")

    appeal = Appeal(application_id=application_id, student_id=student.id, reason=data.reason)
    db.add(appeal)
    await db.commit()
    await db.refresh(appeal)
    return appeal


async def review_appeal(
    db: AsyncSession, application_id: int, data: AppealReview, staff: User
) -> Appeal:
    result = await db.execute(select(Appeal).where(Appeal.application_id == application_id))
    appeal = result.scalar_one_or_none()
    if not appeal:
        raise NotFoundError("Appeal")

    appeal.status = AppealStatus.approved if data.approved else AppealStatus.denied
    appeal.review_note = data.review_note
    appeal.reviewed_by = staff.id
    appeal.reviewed_at = datetime.now(timezone.utc)

    if data.approved:
        app = await _get_application(db, application_id)
        app.status = ApplicationStatus.pending
        # Reset workflow to allow re-entry: move back to APPLICATION/SUBMITTED
        if app.main_status is not None:
            log = WorkflowLog(
                application_id=app.id,
                changed_by=staff.id,
                from_main=app.main_status,
                from_sub=app.sub_status,
                to_main=MainStatus.APPLICATION,
                to_sub=SubStatus.SUBMITTED,
                note=f"Appeal approved: {data.review_note}",
            )
            db.add(log)
            app.main_status = MainStatus.APPLICATION
            app.sub_status = SubStatus.SUBMITTED
            app.closed_at = None
        await append_audit(db, application_id, staff.id, "appeal_approved", from_status=ApplicationStatus.rejected, to_status=ApplicationStatus.pending, note=data.review_note)

    await db.commit()
    await db.refresh(appeal)
    return appeal


async def get_audit_trail(db: AsyncSession, application_id: int, user: User):
    from app.models.audit import AuditEntry
    await get_application(db, application_id, user)  # permission check
    result = await db.execute(
        select(AuditEntry).where(AuditEntry.application_id == application_id).order_by(AuditEntry.created_at)
    )
    return result.scalars().all()
