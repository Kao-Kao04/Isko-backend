"""
Strict state machine service for scholarship application workflow.

Every status transition goes through transition() — no direct status writes allowed.
All transitions are logged in workflow_logs for full auditability.
"""
import asyncio
from datetime import datetime, timezone
from typing import Literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings

from app.models.application import Application, ApplicationStatus, WorkflowLog, CompletionRequirement
from app.models.notification import Notification
from app.models.scholar import Scholar, ScholarStatus, ScholarStatusLog
from app.models.scholarship import ComplianceDocumentType
from app.models.workflow import MainStatus, SubStatus, ALLOWED_TRANSITIONS, can_transition, is_terminal
from app.models.user import User, UserRole
from app.exceptions import ValidationError, NotFoundError, ForbiddenError


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _get_app(db: AsyncSession, application_id: int) -> Application:
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Application)
        .options(selectinload(Application.scholarship), selectinload(Application.student))
        .where(Application.id == application_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise NotFoundError("Application", application_id)
    return app


async def _log(
    db: AsyncSession,
    app: Application,
    actor: User,
    to_main: MainStatus,
    to_sub: SubStatus,
    note: str | None = None,
) -> None:
    db.add(WorkflowLog(
        application_id=app.id,
        changed_by=actor.id,
        from_main=app.main_status,
        from_sub=app.sub_status,
        to_main=to_main,
        to_sub=to_sub,
        note=note,
    ))


def _assert_can_transition(app: Application, to_main: MainStatus, to_sub: SubStatus) -> None:
    if app.main_status is None:
        raise ValidationError("Application has not entered the new workflow yet.")
    if is_terminal(app.main_status, app.sub_status):
        raise ValidationError(
            f"Application is already in a terminal state: {app.main_status}/{app.sub_status}"
        )
    if not can_transition(app.main_status, app.sub_status, to_main, to_sub):
        raise ValidationError(
            f"Invalid transition: {app.main_status}/{app.sub_status} → {to_main}/{to_sub}. "
            f"Allowed: {ALLOWED_TRANSITIONS.get((app.main_status, app.sub_status), [])}"
        )


def _assert_student_owns(app: Application, actor: User) -> None:
    if actor.role == UserRole.student and app.student_id != actor.id:
        raise ForbiddenError("You do not have access to this application")


def _assert_dept(app: Application, actor: User) -> None:
    """OSFA staff may only act on applications for their department's scholarships."""
    if actor.role == UserRole.osfa_staff and actor.department and app.scholarship:
        if app.scholarship.category != actor.department:
            raise ForbiddenError(
                "You can only manage applications for your department's scholarships"
            )


def _queue_notification(
    db: AsyncSession, user_id: int, title: str, body: str, application_id: int
) -> Notification:
    """Add notification to the current session. Caller must commit then push WS."""
    notif = Notification(user_id=user_id, title=title, body=body, application_id=application_id)
    db.add(notif)
    return notif


async def _push_ws(notif: Notification) -> None:
    from app.websocket import manager
    await manager.send(notif.user_id, {
        "type": "notification",
        "id": notif.id,
        "title": notif.title,
        "body": notif.body,
        "application_id": notif.application_id,
    })


async def _commit_and_notify(
    db: AsyncSession, app: Application, notif: Notification | None = None
) -> Application:
    """Single commit for both state + notification, then push WS."""
    await db.commit()
    await db.refresh(app)
    if notif is not None:
        await db.refresh(notif)
        await _push_ws(notif)
    return app


async def _apply(
    db: AsyncSession,
    app: Application,
    actor: User,
    to_main: MainStatus,
    to_sub: SubStatus,
    note: str | None = None,
) -> Application:
    _assert_can_transition(app, to_main, to_sub)
    await _log(db, app, actor, to_main, to_sub, note)
    app.main_status = to_main
    app.sub_status = to_sub
    return app


def _sch_name(app: Application) -> str:
    return app.scholarship.name if app.scholarship else "the scholarship"


def _student_name(app: Application) -> str:
    if app.student and app.student.student_profile:
        p = app.student.student_profile
        return f"{p.first_name} {p.last_name}"
    return f"Student #{app.student_id}"


async def _notify_osfa_staff(db: AsyncSession, app: Application, title: str, body: str) -> None:
    """Notify all active OSFA staff who manage this scholarship's category."""
    from app.services.notification_service import create_notification
    if not app.scholarship:
        return
    category = app.scholarship.category
    result = await db.execute(
        select(User).where(
            User.role == UserRole.osfa_staff,
            User.is_active == True,
            User.department == category,
        )
    )
    for staff in result.scalars().all():
        await create_notification(db, staff.id, title, body, app.id)


# ─── Public API ──────────────────────────────────────────────────────────────

async def initialize_workflow(db: AsyncSession, application_id: int, actor: User) -> Application:
    app = await _get_app(db, application_id)
    if app.main_status is not None:
        raise ValidationError("Workflow already initialized for this application.")
    await _log(db, app, actor, MainStatus.APPLICATION, SubStatus.SUBMITTED)
    app.main_status = MainStatus.APPLICATION
    app.sub_status = SubStatus.SUBMITTED
    return await _commit_and_notify(db, app)


async def start_screening(db: AsyncSession, application_id: int, actor: User) -> Application:
    app = await _get_app(db, application_id)
    _assert_dept(app, actor)
    await _apply(db, app, actor, MainStatus.APPLICATION, SubStatus.SCREENING)
    app.screened_at = _now()
    return await _commit_and_notify(db, app)


async def complete_screening(
    db: AsyncSession, application_id: int, actor: User, passed: bool, note: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    _assert_dept(app, actor)
    if passed:
        await _apply(db, app, actor, MainStatus.APPLICATION, SubStatus.SCREENING_PASSED, note)
        return await _commit_and_notify(db, app)
    else:
        await _apply(db, app, actor, MainStatus.APPLICATION, SubStatus.SCREENING_FAILED, note)
        await _apply(db, app, actor, MainStatus.REJECTED, SubStatus.REJECTED, note)
        app.closed_at = _now()
        app.status = ApplicationStatus.rejected
        notif = _queue_notification(
            db, app.student_id,
            "Application Screened Out",
            f"Your application for {_sch_name(app)} did not pass the initial screening.",
            app.id,
        )
        return await _commit_and_notify(db, app, notif)


async def start_verification(db: AsyncSession, application_id: int, actor: User) -> Application:
    app = await _get_app(db, application_id)
    _assert_dept(app, actor)
    await _apply(db, app, actor, MainStatus.VERIFICATION, SubStatus.PENDING_VALIDATION)
    notif = _queue_notification(
        db, app.student_id,
        "Document Verification Started",
        f"OSFA is now reviewing your documents for {_sch_name(app)}.",
        app.id,
    )
    return await _commit_and_notify(db, app, notif)


async def request_revision(
    db: AsyncSession, application_id: int, actor: User, note: str
) -> Application:
    app = await _get_app(db, application_id)
    _assert_dept(app, actor)
    await _apply(db, app, actor, MainStatus.VERIFICATION, SubStatus.REVISION_REQUESTED, note)
    app.status = ApplicationStatus.incomplete
    notif = _queue_notification(
        db, app.student_id,
        "Document Revision Required",
        f"OSFA has requested revisions for your application: {note or 'Please review and resubmit your documents.'}",
        app.id,
    )
    return await _commit_and_notify(db, app, notif)


async def complete_verification(
    db: AsyncSession, application_id: int, actor: User, passed: bool, note: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    _assert_dept(app, actor)
    if passed:
        await _apply(db, app, actor, MainStatus.VERIFICATION, SubStatus.VALIDATED, note)
        app.validated_at = _now()
        notif = _queue_notification(
            db, app.student_id,
            "Documents Verified",
            f"Your documents for {_sch_name(app)} have been verified successfully.",
            app.id,
        )
        return await _commit_and_notify(db, app, notif)
    else:
        await _apply(db, app, actor, MainStatus.VERIFICATION, SubStatus.VALIDATION_FAILED, note)
        await _apply(db, app, actor, MainStatus.REJECTED, SubStatus.REJECTED, note)
        app.closed_at = _now()
        app.status = ApplicationStatus.rejected
        notif = _queue_notification(
            db, app.student_id,
            "Thank You for Your Application",
            f"Thank you for applying for {_sch_name(app)}. After reviewing your submitted documents, we regret that we are unable to proceed with your application at this time. We encourage you to keep applying in future scholarship cycles.",
            app.id,
        )
        return await _commit_and_notify(db, app, notif)


async def open_interview_scheduling(db: AsyncSession, application_id: int, actor: User) -> Application:
    app = await _get_app(db, application_id)
    _assert_dept(app, actor)
    await _apply(db, app, actor, MainStatus.INTERVIEW, SubStatus.NOT_SCHEDULED)
    notif = _queue_notification(
        db, app.student_id,
        "Interview Scheduling Open",
        f"You can now schedule your interview for {_sch_name(app)}. Please select a time slot.",
        app.id,
    )
    return await _commit_and_notify(db, app, notif)


async def schedule_interview(
    db: AsyncSession,
    application_id: int,
    actor: User,
    interview_datetime: datetime,
    location: str | None = None,
    note: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    # Students can only schedule their own; OSFA can schedule for their dept
    if actor.role == UserRole.student:
        _assert_student_owns(app, actor)
    else:
        _assert_dept(app, actor)

    if actor.role == UserRole.osfa_staff or actor.role == UserRole.super_admin:
        allowed_states = (SubStatus.NOT_SCHEDULED, SubStatus.RESCHEDULED, SubStatus.SCHEDULED)
    else:
        allowed_states = (SubStatus.NOT_SCHEDULED, SubStatus.RESCHEDULED)
    if app.sub_status not in allowed_states:
        raise ValidationError(f"Cannot schedule interview from state {app.sub_status}")

    if interview_datetime <= _now():
        raise ValidationError("Interview must be scheduled for a future date and time")

    # If already SCHEDULED, OSFA is updating the datetime — skip transition check, just update
    if app.sub_status == SubStatus.SCHEDULED and actor.role in (UserRole.osfa_staff, UserRole.super_admin):
        await _log(db, app, actor, MainStatus.INTERVIEW, SubStatus.SCHEDULED, note)
    else:
        await _apply(db, app, actor, MainStatus.INTERVIEW, SubStatus.SCHEDULED, note)
    app.interview_datetime = interview_datetime
    app.interview_scheduled_at = _now()
    if location:
        app.interview_location = location
    dt_str = interview_datetime.strftime('%B %d, %Y at %I:%M %p')
    notif = _queue_notification(
        db, app.student_id,
        "Interview Scheduled",
        f"Your interview for {_sch_name(app)} has been scheduled on {dt_str}.",
        app.id,
    )
    if actor.role == UserRole.student:
        await _notify_osfa_staff(db, app, "Interview Scheduled by Student",
            f"{_student_name(app)} scheduled their interview for {_sch_name(app)} on {dt_str}.")
    else:
        # OSFA scheduled — email the student
        if app.student:
            from app.utils.email import _send
            location_line = f"<p><strong>Location:</strong> {app.interview_location}</p>" if app.interview_location else ""
            asyncio.create_task(_send(
                app.student.email,
                f"Interview Scheduled — {_sch_name(app)}",
                f"""<div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px;">
                <h2 style="color:#800000;">Interview Scheduled</h2>
                <p>Hi {_student_name(app)},</p>
                <p>Your interview for <strong>{_sch_name(app)}</strong> has been scheduled.</p>
                <p><strong>Date &amp; Time:</strong> {dt_str}</p>
                {location_line}
                <a href="{settings.FRONTEND_URL}/student/applications/{app.id}"
                   style="display:inline-block;padding:12px 28px;background:#800000;color:#fff;
                          text-decoration:none;border-radius:8px;font-weight:bold;margin:16px 0;">
                    View Application
                </a>
                <p style="color:#6b7280;font-size:13px;">Polytechnic University of the Philippines — OSFA</p>
                </div>"""
            ))
    return await _commit_and_notify(db, app, notif)


async def reschedule_interview(
    db: AsyncSession, application_id: int, actor: User, reason: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    _assert_student_owns(app, actor)

    if app.sub_status not in (SubStatus.SCHEDULED, SubStatus.RESCHEDULED):
        raise ValidationError("Can only reschedule a SCHEDULED or RESCHEDULED interview.")
    await _apply(db, app, actor, MainStatus.INTERVIEW, SubStatus.RESCHEDULED, reason)
    await _notify_osfa_staff(db, app, "Reschedule Requested",
        f"{_student_name(app)} requested an interview reschedule for {_sch_name(app)}.")
    notif = _queue_notification(
        db, app.student_id,
        "Interview Rescheduled",
        f"Your interview for {_sch_name(app)} has been marked for rescheduling.",
        app.id,
    )
    return await _commit_and_notify(db, app, notif)


async def complete_interview(
    db: AsyncSession, application_id: int, actor: User, notes: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    _assert_dept(app, actor)
    if not app.interview_datetime:
        raise ValidationError("Cannot complete interview — no interview schedule exists.")
    if app.sub_status != SubStatus.SCHEDULED:
        raise ValidationError("Interview must be in SCHEDULED state to be completed.")
    await _apply(db, app, actor, MainStatus.INTERVIEW, SubStatus.INTERVIEW_COMPLETED, notes)
    app.interview_completed_at = _now()
    if notes:
        app.interview_notes = notes
    return await _commit_and_notify(db, app)


async def submit_evaluation(
    db: AsyncSession,
    application_id: int,
    actor: User,
    eval_score: dict | None = None,
    note: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    _assert_dept(app, actor)
    if app.sub_status != SubStatus.INTERVIEW_COMPLETED:
        raise ValidationError("Cannot evaluate before interview is completed.")
    await _apply(db, app, actor, MainStatus.INTERVIEW, SubStatus.EVALUATED, note)
    app.evaluated_at = _now()
    if eval_score:
        app.eval_score = eval_score
    return await _commit_and_notify(db, app)


async def move_to_review(db: AsyncSession, application_id: int, actor: User) -> Application:
    app = await _get_app(db, application_id)
    _assert_dept(app, actor)
    if app.sub_status != SubStatus.EVALUATED:
        raise ValidationError("Cannot move to review — evaluation not yet submitted.")
    await _apply(db, app, actor, MainStatus.DECISION, SubStatus.UNDER_REVIEW)
    return await _commit_and_notify(db, app)


async def release_decision(
    db: AsyncSession,
    application_id: int,
    actor: User,
    decision: Literal["approved", "rejected", "waitlisted"],
    remarks: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    _assert_dept(app, actor)

    decision_map = {
        "approved":   SubStatus.APPROVED,
        "rejected":   SubStatus.REJECTED,
        "waitlisted": SubStatus.WAITLISTED,
    }
    if decision not in decision_map:
        raise ValidationError(f"Invalid decision '{decision}'. Must be: approved, rejected, waitlisted")

    to_sub = decision_map[decision]
    await _apply(db, app, actor, MainStatus.DECISION, to_sub, remarks)
    app.decision_released_at = _now()
    if remarks:
        app.decision_remarks = remarks

    if decision == "rejected":
        app.closed_at = _now()
        app.status = ApplicationStatus.rejected
        notif = _queue_notification(
            db, app.student_id,
            "Thank You for Your Application",
            (f"Thank you for taking the time to apply for {_sch_name(app)}. After careful deliberation, we regret to inform you that you were not selected as a recipient for this cycle. We appreciate your effort and encourage you to apply again in the future. {remarks}".strip() if remarks else f"Thank you for taking the time to apply for {_sch_name(app)}. After careful deliberation, we regret to inform you that you were not selected as a recipient for this cycle. We appreciate your effort and encourage you to apply again in the future."),
            app.id,
        )
        if app.student:
            from app.utils.email import _send
            remarks_block = f"<p><strong>Remarks:</strong> {remarks}</p>" if remarks else ""
            asyncio.create_task(_send(
                app.student.email,
                f"Application Update — {_sch_name(app)}",
                f"""<div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px;">
                <h2 style="color:#800000;">Thank You for Applying</h2>
                <p>Hi {_student_name(app)},</p>
                <p>Thank you for applying for <strong>{_sch_name(app)}</strong>. After careful deliberation, we regret to inform you that you were not selected as a recipient for this cycle.</p>
                {remarks_block}
                <p>We appreciate your effort and encourage you to apply again in the future.</p>
                <p style="color:#6b7280;font-size:13px;">Polytechnic University of the Philippines — OSFA</p>
                </div>"""
            ))
        return await _commit_and_notify(db, app, notif)

    if decision == "waitlisted":
        notif = _queue_notification(
            db, app.student_id,
            "Application Waitlisted",
            f"Your application for {_sch_name(app)} has been waitlisted. You will be notified if a slot becomes available.",
            app.id,
        )
        if app.student:
            from app.utils.email import _send
            asyncio.create_task(_send(
                app.student.email,
                f"Application Waitlisted — {_sch_name(app)}",
                f"""<div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px;">
                <h2 style="color:#800000;">Application Waitlisted</h2>
                <p>Hi {_student_name(app)},</p>
                <p>Your application for <strong>{_sch_name(app)}</strong> has been waitlisted. You will be notified if a slot becomes available.</p>
                <a href="{settings.FRONTEND_URL}/student/applications/{app.id}"
                   style="display:inline-block;padding:12px 28px;background:#800000;color:#fff;
                          text-decoration:none;border-radius:8px;font-weight:bold;margin:16px 0;">
                    View Application
                </a>
                <p style="color:#6b7280;font-size:13px;">Polytechnic University of the Philippines — OSFA</p>
                </div>"""
            ))
        return await _commit_and_notify(db, app, notif)

    # Approved: create Scholar record and auto-progress to COMPLETION
    existing = await db.execute(select(Scholar).where(Scholar.application_id == app.id))
    if not existing.scalar_one_or_none():
        db.add(Scholar(
            application_id=app.id,
            student_id=app.student_id,
            scholarship_id=app.scholarship_id,
        ))

    app.status = ApplicationStatus.approved
    await _apply(db, app, actor, MainStatus.COMPLETION, SubStatus.PENDING_REQUIREMENTS)
    notif = _queue_notification(
        db, app.student_id,
        "Application Approved — Congratulations!",
        f"Your application for {_sch_name(app)} has been approved! Please submit the required completion documents.",
        app.id,
    )
    if app.student:
        from app.utils.email import _send
        asyncio.create_task(_send(
            app.student.email,
            f"Congratulations! Application Approved — {_sch_name(app)}",
            f"""<div style="font-family:sans-serif;max-width:480px;margin:0 auto;padding:32px;">
            <h2 style="color:#800000;">Congratulations!</h2>
            <p>Hi {_student_name(app)},</p>
            <p>We are pleased to inform you that your application for <strong>{_sch_name(app)}</strong> has been <strong>approved</strong>!</p>
            <p>Please log in to IskoMo and submit the required completion documents to finalize your scholar onboarding.</p>
            <a href="{settings.FRONTEND_URL}/student/applications/{app.id}"
               style="display:inline-block;padding:12px 28px;background:#800000;color:#fff;
                      text-decoration:none;border-radius:8px;font-weight:bold;margin:16px 0;">
                Submit Documents
            </a>
            <p style="color:#6b7280;font-size:13px;">Polytechnic University of the Philippines — OSFA</p>
            </div>"""
        ))
    return await _commit_and_notify(db, app, notif)


async def submit_completion_requirements(
    db: AsyncSession,
    application_id: int,
    actor: User,
    requirements: list[dict],
) -> Application:
    app = await _get_app(db, application_id)
    _assert_student_owns(app, actor)

    if app.sub_status != SubStatus.PENDING_REQUIREMENTS:
        raise ValidationError("Not in PENDING_REQUIREMENTS state.")
    if not requirements:
        raise ValidationError("At least one completion requirement must be submitted.")

    for req in requirements:
        db.add(CompletionRequirement(
            application_id=application_id,
            requirement_type=req["requirement_type"],
            file_url=req.get("file_url"),
            submitted_at=_now(),
        ))

    await _apply(db, app, actor, MainStatus.COMPLETION, SubStatus.REQUIREMENTS_SUBMITTED)
    app.completion_submitted_at = _now()
    await _notify_osfa_staff(db, app, "Requirements Submitted",
        f"{_student_name(app)} submitted completion requirements for {_sch_name(app)}.")
    return await _commit_and_notify(db, app)


async def finalize(
    db: AsyncSession, application_id: int, actor: User, note: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    _assert_dept(app, actor)
    if app.sub_status != SubStatus.REQUIREMENTS_SUBMITTED:
        raise ValidationError("Requirements must be submitted before finalizing.")

    # Verify all required compliance docs are verified before finalizing
    required_types = (await db.execute(
        select(ComplianceDocumentType.name).where(
            ComplianceDocumentType.scholarship_id == app.scholarship_id,
            ComplianceDocumentType.is_required == True,
        )
    )).scalars().all()
    if required_types:
        unverified = (await db.execute(
            select(CompletionRequirement).where(
                CompletionRequirement.application_id == application_id,
                CompletionRequirement.requirement_type.in_(required_types),
                CompletionRequirement.is_verified == False,
            )
        )).scalars().all()
        if unverified:
            names = ", ".join(r.requirement_type for r in unverified)
            raise ValidationError(f"Cannot finalize — unverified compliance documents: {names}")

    await _apply(db, app, actor, MainStatus.COMPLETION, SubStatus.COMPLETED, note)
    app.closed_at = _now()

    # Auto-activate the scholar record
    scholar_result = await db.execute(
        select(Scholar).where(Scholar.application_id == application_id)
    )
    scholar = scholar_result.scalar_one_or_none()
    if scholar and scholar.status == ScholarStatus.active:
        pass  # already active from release_decision
    elif scholar:
        db.add(ScholarStatusLog(
            scholar_id=scholar.id,
            from_status=scholar.status,
            to_status=ScholarStatus.active,
            actor_id=actor.id,
            reason="Compliance documents verified — scholar officially activated",
        ))
        scholar.status = ScholarStatus.active

    notif = _queue_notification(
        db, app.student_id,
        "Scholarship Compliance Complete — Welcome!",
        f"All compliance documents for {_sch_name(app)} have been verified. You are now an official scholar!",
        app.id,
    )
    return await _commit_and_notify(db, app, notif)


async def withdraw(
    db: AsyncSession, application_id: int, actor: User, reason: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    _assert_student_owns(app, actor)

    if is_terminal(app.main_status, app.sub_status):
        raise ValidationError("Cannot withdraw — application is already in a terminal state.")

    await _log(db, app, actor, MainStatus.WITHDRAWN, SubStatus.WITHDRAWN, reason)
    app.main_status = MainStatus.WITHDRAWN
    app.sub_status = SubStatus.WITHDRAWN
    app.closed_at = _now()
    app.status = ApplicationStatus.withdrawn
    return await _commit_and_notify(db, app)


async def get_workflow_logs(db: AsyncSession, application_id: int) -> list[WorkflowLog]:
    result = await db.execute(
        select(WorkflowLog)
        .where(WorkflowLog.application_id == application_id)
        .order_by(WorkflowLog.created_at)
    )
    return result.scalars().all()
