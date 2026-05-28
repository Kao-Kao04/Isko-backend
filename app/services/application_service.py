from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload

from app.models.application import Application, ApplicationStatus, WorkflowLog
from app.models.scholarship import Scholarship, ScholarshipStatus
from app.models.scholar import Scholar
from app.models.appeal import Appeal, AppealStatus
from app.models.user import User, UserRole, StudentProfile
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
    if scholarship.min_gwa:
        if not student_profile.gwa:
            raise ValidationError(
                f"Not eligible: GWA is not set. Minimum requirement is {scholarship.min_gwa}"
            )
        try:
            student_gwa = float(student_profile.gwa)
            required_gwa = float(scholarship.min_gwa)
            if student_gwa > required_gwa:
                raise ValidationError(
                    f"Not eligible: GWA of {student_profile.gwa} does not meet the minimum requirement of {scholarship.min_gwa}"
                )
        except (ValueError, TypeError):
            raise ValidationError(
                f"Not eligible: GWA value '{student_profile.gwa}' could not be verified against the minimum requirement of {scholarship.min_gwa}"
            )


async def list_applications(
    db: AsyncSession,
    user: User,
    page: int,
    page_size: int,
    status: str | None = None,
    search: str | None = None,
    scholarship_id: int | None = None,
):
    q = select(Application)
    if user.role == UserRole.student:
        q = q.where(Application.student_id == user.id)
    if user.role == UserRole.osfa_staff and user.department:
        q = (q
            .join(Scholarship, Application.scholarship_id == Scholarship.id)
            .where(Scholarship.category == user.department.value))
    if scholarship_id:
        q = q.where(Application.scholarship_id == scholarship_id)
    if status:
        try:
            q = q.where(Application.status == ApplicationStatus(status))
        except ValueError:
            pass
    if search:
        term = f"%{search.strip()}%"
        q = (q
            .join(User, Application.student_id == User.id, isouter=False)
            .outerjoin(StudentProfile, User.id == StudentProfile.user_id)
            .where(or_(
                User.email.ilike(term),
                StudentProfile.first_name.ilike(term),
                StudentProfile.last_name.ilike(term),
                func.concat(StudentProfile.first_name, ' ', StudentProfile.last_name).ilike(term),
            )))

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
    if user.role == UserRole.student:
        app.interview_notes = None  # type: ignore[assignment]
    if user.role == UserRole.osfa_staff and user.department:
        _check_department_ownership(app, user)
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


    existing = await db.execute(
        select(Application).where(
            Application.student_id == student.id,
            Application.scholarship_id == data.scholarship_id,
            Application.status.notin_([ApplicationStatus.withdrawn]),
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError("Already applied to this scholarship")

    # One active application per category (public/private)
    if scholarship.category:
        cat_conflict = await db.execute(
            select(Application)
            .join(Scholarship, Application.scholarship_id == Scholarship.id)
            .where(
                Application.student_id == student.id,
                Application.status.notin_([ApplicationStatus.withdrawn, ApplicationStatus.rejected]),
                Scholarship.category == scholarship.category,
            )
        )
        if cat_conflict.scalar_one_or_none():
            label = scholarship.category.value.capitalize()
            raise ConflictError(f"You already have an active application for a {label} scholarship. You may only apply to one per category.")

    from sqlalchemy.exc import IntegrityError
    app = Application(student_id=student.id, scholarship_id=data.scholarship_id, essay_text=data.essay_text)
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

    # Notify student
    await create_notification(
        db, student.id, "Application Submitted",
        f"Your application for {scholarship.name} has been submitted.", app.id
    )

    # Notify OSFA staff in matching department
    student_label = f"{student.student_profile.first_name} {student.student_profile.last_name}".strip() if student.student_profile else student.email
    if scholarship.category:
        osfa_staff = (await db.execute(
            select(User).where(User.role == UserRole.osfa_staff, User.is_active == True, User.department == scholarship.category)
        )).scalars().all()
        for s in osfa_staff:
            await create_notification(
                db, s.id,
                "New Application Received",
                f"{student_label} applied for {scholarship.name}",
                app.id,
                link=f"/applicants/{app.id}",
            )

    await db.commit()
    return await _get_application(db, app.id)


async def resubmit_application(db: AsyncSession, application_id: int, student: User) -> Application:
    app = await _get_application(db, application_id)
    if app.student_id != student.id:
        raise ForbiddenError()
    if app.status != ApplicationStatus.incomplete:
        raise ValidationError("Can only resubmit Incomplete applications")

    # Re-run eligibility check so profile changes don't bypass scholarship criteria
    if app.scholarship and student.student_profile:
        _check_eligibility(app.scholarship, student.student_profile)

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
    sch_name = scholarship.name if scholarship else "the scholarship"

    # Notify student
    await create_notification(
        db, student.id, "Application Resubmitted",
        f"Your application for {sch_name} has been resubmitted.", app.id
    )

    # Notify OSFA — student fixed their documents
    student_label = student.email
    if student.student_profile:
        student_label = f"{student.student_profile.first_name} {student.student_profile.last_name}".strip() or student.email
    if scholarship and scholarship.category:
        osfa_staff = (await db.execute(
            select(User).where(User.role == UserRole.osfa_staff, User.is_active == True, User.department == scholarship.category)
        )).scalars().all()
        for s in osfa_staff:
            await create_notification(
                db, s.id,
                "Application Resubmitted",
                f"{student_label} resubmitted their application for {sch_name}",
                app.id,
                link=f"/applicants/{app.id}",
            )

    await db.commit()
    return await _get_application(db, app.id)


async def withdraw_application(db: AsyncSession, application_id: int, student: User) -> None:
    app = await _get_application(db, application_id)
    if app.student_id != student.id:
        raise ForbiddenError()
    # Block if application is in a terminal workflow state
    if app.main_status in (MainStatus.DECISION, MainStatus.COMPLETION):
        if app.sub_status in (SubStatus.APPROVED, SubStatus.REJECTED, SubStatus.COMPLETED):
            raise ValidationError("Cannot withdraw an application that has already been decided.")
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

    # Block the legacy status endpoint once the new workflow has been initialized.
    # All state changes must go through /api/workflow/* from that point on.
    if app.main_status is not None:
        raise ValidationError(
            "This application is managed by the workflow system. "
            "Use the /api/workflow endpoints to update its status."
        )

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
        ApplicationStatus.rejected: ("Thank You for Your Application", f"Thank you for applying for {sch_name}. After careful review, we regret that your application was not successful at this time. We encourage you to apply again in future scholarship cycles."),
        ApplicationStatus.incomplete: ("Application Incomplete", f"Your application for {sch_name} requires additional documents."),
    }
    title, body = notif_map[data.status]
    await create_notification(db, app.student_id, title, body, app.id)

    # Notify all OSFA staff in the same department so the team is aware (#11)
    if scholarship and scholarship.category:
        from app.models.user import UserRole as _Role
        staff_result = await db.execute(
            select(User).where(
                User.role == _Role.osfa_staff,
                User.is_active == True,
                User.department == scholarship.category,
            )
        )
        student_result = await db.execute(select(User).where(User.id == app.student_id))
        student = student_result.scalar_one_or_none()
        student_label = student.email if student else f"Student #{app.student_id}"
        osfa_notif_map = {
            ApplicationStatus.approved:    f"Application approved: {student_label} — {sch_name}",
            ApplicationStatus.rejected:    f"Application rejected: {student_label} — {sch_name}",
            ApplicationStatus.incomplete:  f"Application marked incomplete: {student_label} — {sch_name}",
        }
        for s in staff_result.scalars().all():
            if s.id != staff.id:  # don't notify the person who took the action
                await create_notification(db, s.id, title, osfa_notif_map[data.status], app.id)

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

    # #14: Appeals allowed only for Application/Verification-stage rejections.
    # Decision-stage rejection is final — no appeal.
    is_early_workflow_rejection = (
        app.main_status == MainStatus.REJECTED        # terminal rejection from Application or Verification screening
        and app.sub_status == SubStatus.REJECTED
    )
    is_legacy_early_rejection = (
        app.status == ApplicationStatus.rejected
        and app.main_status not in (MainStatus.DECISION,)
    )
    if not is_early_workflow_rejection and not is_legacy_early_rejection:
        raise ValidationError(
            "Appeals are only allowed for Application or Verification stage rejections. "
            "Decision-stage rejections are final."
        )

    existing = await db.execute(select(Appeal).where(Appeal.application_id == application_id))
    if existing.scalar_one_or_none():
        raise ConflictError("Appeal already filed")

    appeal = Appeal(application_id=application_id, student_id=student.id, reason=data.reason)
    db.add(appeal)

    # #12: Notify OSFA staff that a student filed an appeal
    sch_result = await db.execute(select(Scholarship).where(Scholarship.id == app.scholarship_id))
    scholarship = sch_result.scalar_one_or_none()
    if scholarship and scholarship.category:
        from app.models.user import UserRole as _Role
        staff_result = await db.execute(
            select(User).where(
                User.role == _Role.osfa_staff,
                User.is_active == True,
                User.department == scholarship.category,
            )
        )
        student_label = student.email
        if student.student_profile:
            student_label = f"{student.student_profile.first_name} {student.student_profile.last_name}"
        sch_name = scholarship.name if scholarship else "a scholarship"
        for s in staff_result.scalars().all():
            await create_notification(
                db, s.id,
                "Appeal Filed",
                f"{student_label} filed an appeal for {sch_name}: {data.reason[:120]}{'…' if len(data.reason) > 120 else ''}",
                app.id,
            )

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

    app_for_dept = await _get_application(db, application_id)
    if staff.role == UserRole.osfa_staff and staff.department:
        _check_department_ownership(app_for_dept, staff)

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

    # Fetch student email and scholarship name for email notification
    _student_email: str | None = None
    _sch_name_appeal: str | None = None
    try:
        from app.models.user import User as _User
        _u = (await db.execute(select(_User).where(_User.id == appeal.student_id))).scalar_one_or_none()
        _student_email = str(_u.email) if _u else None
        _app_for_name = await db.execute(
            select(Application).where(Application.id == application_id)
        )
        _a = _app_for_name.scalar_one_or_none()
        if _a and _a.scholarship_id:
            _s = (await db.execute(select(Scholarship).where(Scholarship.id == _a.scholarship_id))).scalar_one_or_none()
            _sch_name_appeal = str(_s.name) if _s else None
    except Exception:
        pass

    # Notify student of appeal outcome
    try:
        if data.approved:
            await create_notification(
                db, appeal.student_id,
                "Appeal Approved",
                "Your appeal has been approved. Your application has been reinstated and will be reviewed again.",
                application_id,
            )
        else:
            note_text = f" Note: {data.review_note}" if data.review_note else ""
            await create_notification(
                db, appeal.student_id,
                "Appeal Denied",
                f"Your appeal was not approved.{note_text} Please contact OSFA for further assistance.",
                application_id,
            )
    except Exception:
        pass

    if _student_email and _sch_name_appeal:
        try:
            from app.utils.email import send_appeal_outcome_email
            await send_appeal_outcome_email(_student_email, _sch_name_appeal, data.approved, data.review_note)
        except Exception:
            pass

    await db.refresh(appeal)
    return appeal


async def get_audit_trail(db: AsyncSession, application_id: int, user: User):
    from app.models.audit import AuditEntry
    await get_application(db, application_id, user)  # permission check
    result = await db.execute(
        select(AuditEntry).where(AuditEntry.application_id == application_id).order_by(AuditEntry.created_at)
    )
    return result.scalars().all()
