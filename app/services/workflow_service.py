"""
Strict state machine service for scholarship application workflow.

Every status transition goes through transition() — no direct status writes allowed.
All transitions are logged in workflow_logs for full auditability.
"""
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.application import Application, WorkflowLog, CompletionRequirement
from app.models.workflow import MainStatus, SubStatus, ALLOWED_TRANSITIONS, can_transition, is_terminal
from app.models.user import User, UserRole
from app.exceptions import ValidationError, NotFoundError, ForbiddenError


# ─── Helpers ─────────────────────────────────────────────────────────────────

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
    log = WorkflowLog(
        application_id=app.id,
        changed_by=actor.id,
        from_main=app.main_status,
        from_sub=app.sub_status,
        to_main=to_main,
        to_sub=to_sub,
        note=note,
    )
    db.add(log)


def _assert_can_transition(
    app: Application,
    to_main: MainStatus,
    to_sub: SubStatus,
) -> None:
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
    """Students may only act on their own applications."""
    if actor.role == UserRole.student and app.student_id != actor.id:
        raise ForbiddenError("You do not have access to this application")


async def _notify(db: AsyncSession, user_id: int, title: str, body: str, application_id: int) -> None:
    from app.services.notification_service import create_notification
    await create_notification(db, user_id, title, body, application_id)


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


# ─── Public API ──────────────────────────────────────────────────────────────

async def initialize_workflow(db: AsyncSession, application_id: int, actor: User) -> Application:
    """Called after student submits. Sets initial workflow state."""
    app = await _get_app(db, application_id)
    if app.main_status is not None:
        raise ValidationError("Workflow already initialized for this application.")
    await _log(db, app, actor, MainStatus.APPLICATION, SubStatus.SUBMITTED)
    app.main_status = MainStatus.APPLICATION
    app.sub_status = SubStatus.SUBMITTED
    await db.commit()
    await db.refresh(app)
    return app


async def start_screening(db: AsyncSession, application_id: int, actor: User) -> Application:
    app = await _get_app(db, application_id)
    await _apply(db, app, actor, MainStatus.APPLICATION, SubStatus.SCREENING)
    app.screened_at = _now()
    await db.commit()
    await db.refresh(app)
    return app


async def complete_screening(
    db: AsyncSession,
    application_id: int,
    actor: User,
    passed: bool,
    note: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    if passed:
        await _apply(db, app, actor, MainStatus.APPLICATION, SubStatus.SCREENING_PASSED, note)
        await db.commit()
        await db.refresh(app)
        return app
    else:
        await _apply(db, app, actor, MainStatus.APPLICATION, SubStatus.SCREENING_FAILED, note)
        # Auto-transition to terminal rejected
        await _apply(db, app, actor, MainStatus.REJECTED, SubStatus.REJECTED, note)
        app.closed_at = _now()
        await db.commit()
        await _notify(
            db, app.student_id,
            "Application Screened Out",
            f"Your application for {app.scholarship.name if app.scholarship else 'the scholarship'} did not pass the initial screening.",
            app.id,
        )
        await db.commit()
        await db.refresh(app)
        return app


async def start_verification(db: AsyncSession, application_id: int, actor: User) -> Application:
    app = await _get_app(db, application_id)
    await _apply(db, app, actor, MainStatus.VERIFICATION, SubStatus.PENDING_VALIDATION)
    await db.commit()
    await _notify(
        db, app.student_id,
        "Document Verification Started",
        f"OSFA is now reviewing your documents for {app.scholarship.name if app.scholarship else 'your scholarship application'}.",
        app.id,
    )
    await db.commit()
    await db.refresh(app)
    return app


async def request_revision(
    db: AsyncSession, application_id: int, actor: User, note: str
) -> Application:
    app = await _get_app(db, application_id)
    await _apply(db, app, actor, MainStatus.VERIFICATION, SubStatus.REVISION_REQUESTED, note)
    # Sync legacy status so students can resubmit
    from app.models.application import ApplicationStatus
    app.status = ApplicationStatus.incomplete
    await db.commit()
    await _notify(
        db, app.student_id,
        "Document Revision Required",
        f"OSFA has requested revisions for your application: {note or 'Please review and resubmit your documents.'}",
        app.id,
    )
    await db.commit()
    await db.refresh(app)
    return app


async def complete_verification(
    db: AsyncSession,
    application_id: int,
    actor: User,
    passed: bool,
    note: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    if passed:
        await _apply(db, app, actor, MainStatus.VERIFICATION, SubStatus.VALIDATED, note)
        app.validated_at = _now()
        await db.commit()
        await _notify(
            db, app.student_id,
            "Documents Verified",
            f"Your documents for {app.scholarship.name if app.scholarship else 'your scholarship application'} have been verified successfully.",
            app.id,
        )
        await db.commit()
        await db.refresh(app)
        return app
    else:
        await _apply(db, app, actor, MainStatus.VERIFICATION, SubStatus.VALIDATION_FAILED, note)
        await _apply(db, app, actor, MainStatus.REJECTED, SubStatus.REJECTED, note)
        app.closed_at = _now()
        # Sync legacy status
        from app.models.application import ApplicationStatus
        app.status = ApplicationStatus.rejected
        await db.commit()
        await _notify(
            db, app.student_id,
            "Application Rejected",
            f"Your application for {app.scholarship.name if app.scholarship else 'the scholarship'} was rejected during document verification.",
            app.id,
        )
        await db.commit()
        await db.refresh(app)
        return app


async def open_interview_scheduling(db: AsyncSession, application_id: int, actor: User) -> Application:
    """OSFA opens interview scheduling after verification."""
    app = await _get_app(db, application_id)
    await _apply(db, app, actor, MainStatus.INTERVIEW, SubStatus.NOT_SCHEDULED)
    await db.commit()
    await _notify(
        db, app.student_id,
        "Interview Scheduling Open",
        f"You can now schedule your interview for {app.scholarship.name if app.scholarship else 'your scholarship application'}. Please select a time slot.",
        app.id,
    )
    await db.commit()
    await db.refresh(app)
    return app


async def schedule_interview(
    db: AsyncSession,
    application_id: int,
    actor: User,
    interview_datetime: datetime,
    location: str | None = None,
    note: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    _assert_student_owns(app, actor)

    current_sub = app.sub_status
    if current_sub in (SubStatus.NOT_SCHEDULED, SubStatus.RESCHEDULED):
        to_sub = SubStatus.SCHEDULED
    else:
        raise ValidationError(f"Cannot schedule interview from state {current_sub}")

    await _apply(db, app, actor, MainStatus.INTERVIEW, to_sub, note)
    app.interview_datetime = interview_datetime
    app.interview_scheduled_at = _now()
    if location:
        app.interview_location = location
    await db.commit()
    await _notify(
        db, app.student_id,
        "Interview Scheduled",
        f"Your interview for {app.scholarship.name if app.scholarship else 'your scholarship application'} has been scheduled on {interview_datetime.strftime('%B %d, %Y at %I:%M %p')}.",
        app.id,
    )
    await db.commit()
    await db.refresh(app)
    return app


async def reschedule_interview(
    db: AsyncSession,
    application_id: int,
    actor: User,
    reason: str,
) -> Application:
    app = await _get_app(db, application_id)
    _assert_student_owns(app, actor)

    if app.sub_status not in (SubStatus.SCHEDULED, SubStatus.RESCHEDULED):
        raise ValidationError("Can only reschedule a SCHEDULED or RESCHEDULED interview.")
    await _apply(db, app, actor, MainStatus.INTERVIEW, SubStatus.RESCHEDULED, reason)
    await db.commit()
    await _notify(
        db, app.student_id,
        "Interview Rescheduled",
        f"Your interview for {app.scholarship.name if app.scholarship else 'your scholarship application'} has been marked for rescheduling.",
        app.id,
    )
    await db.commit()
    await db.refresh(app)
    return app


async def complete_interview(
    db: AsyncSession,
    application_id: int,
    actor: User,
    notes: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)

    if not app.interview_datetime:
        raise ValidationError("Cannot complete interview — no interview schedule exists.")
    if app.sub_status != SubStatus.SCHEDULED:
        raise ValidationError("Interview must be in SCHEDULED state to be completed.")

    await _apply(db, app, actor, MainStatus.INTERVIEW, SubStatus.INTERVIEW_COMPLETED, notes)
    app.interview_completed_at = _now()
    if notes:
        app.interview_notes = notes
    await db.commit()
    await db.refresh(app)
    return app


async def submit_evaluation(
    db: AsyncSession,
    application_id: int,
    actor: User,
    eval_score: dict | None = None,
    note: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    if app.sub_status != SubStatus.INTERVIEW_COMPLETED:
        raise ValidationError("Cannot evaluate before interview is completed.")

    await _apply(db, app, actor, MainStatus.INTERVIEW, SubStatus.EVALUATED, note)
    app.evaluated_at = _now()
    if eval_score:
        app.eval_score = eval_score
    await db.commit()
    await db.refresh(app)
    return app


async def move_to_review(db: AsyncSession, application_id: int, actor: User) -> Application:
    app = await _get_app(db, application_id)
    if app.sub_status != SubStatus.EVALUATED:
        raise ValidationError("Cannot move to review — evaluation not yet submitted.")
    await _apply(db, app, actor, MainStatus.DECISION, SubStatus.UNDER_REVIEW)
    await db.commit()
    await db.refresh(app)
    return app


async def release_decision(
    db: AsyncSession,
    application_id: int,
    actor: User,
    decision: str,   # "approved" | "rejected" | "waitlisted"
    remarks: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)

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

    sch_name = app.scholarship.name if app.scholarship else "the scholarship"

    if decision == "rejected":
        # DECISION/REJECTED is terminal — mark closed and sync legacy status
        app.closed_at = _now()
        from app.models.application import ApplicationStatus
        app.status = ApplicationStatus.rejected
        await db.commit()
        await _notify(
            db, app.student_id,
            "Application Decision: Not Selected",
            f"We regret to inform you that your application for {sch_name} was not selected. {remarks or ''}".strip(),
            app.id,
        )
        await db.commit()
        await db.refresh(app)
        return app

    if decision == "waitlisted":
        await db.commit()
        await _notify(
            db, app.student_id,
            "Application Waitlisted",
            f"Your application for {sch_name} has been waitlisted. You will be notified if a slot becomes available.",
            app.id,
        )
        await db.commit()
        await db.refresh(app)
        return app

    # Approved: create Scholar record and auto-progress to COMPLETION
    from app.models.scholar import Scholar
    from sqlalchemy.exc import IntegrityError
    existing = await db.execute(select(Scholar).where(Scholar.application_id == app.id))
    if not existing.scalar_one_or_none():
        scholar = Scholar(
            application_id=app.id,
            student_id=app.student_id,
            scholarship_id=app.scholarship_id,
        )
        db.add(scholar)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()

    # Sync legacy status
    from app.models.application import ApplicationStatus
    app.status = ApplicationStatus.approved

    await _apply(db, app, actor, MainStatus.COMPLETION, SubStatus.PENDING_REQUIREMENTS)
    await db.commit()
    await _notify(
        db, app.student_id,
        "Application Approved — Congratulations!",
        f"Your application for {sch_name} has been approved! Please submit the required completion documents.",
        app.id,
    )
    await db.commit()
    await db.refresh(app)
    return app


async def submit_completion_requirements(
    db: AsyncSession,
    application_id: int,
    actor: User,
    requirements: list[dict],  # [{"requirement_type": "...", "file_url": "..."}]
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
    await db.commit()
    await db.refresh(app)
    return app


async def finalize(
    db: AsyncSession,
    application_id: int,
    actor: User,
    note: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    if app.sub_status != SubStatus.REQUIREMENTS_SUBMITTED:
        raise ValidationError("Requirements must be submitted before finalizing.")
    await _apply(db, app, actor, MainStatus.COMPLETION, SubStatus.COMPLETED, note)
    app.closed_at = _now()
    await db.commit()
    await _notify(
        db, app.student_id,
        "Scholarship Completed",
        f"Your scholarship for {app.scholarship.name if app.scholarship else 'the scholarship'} has been finalized. Congratulations!",
        app.id,
    )
    await db.commit()
    await db.refresh(app)
    return app


async def withdraw(
    db: AsyncSession,
    application_id: int,
    actor: User,
    reason: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    _assert_student_owns(app, actor)

    if is_terminal(app.main_status, app.sub_status):
        raise ValidationError("Cannot withdraw — application is already in a terminal state.")

    await _log(db, app, actor, MainStatus.WITHDRAWN, SubStatus.WITHDRAWN, reason)
    app.main_status = MainStatus.WITHDRAWN
    app.sub_status = SubStatus.WITHDRAWN
    app.closed_at = _now()
    # Sync legacy status
    from app.models.application import ApplicationStatus
    app.status = ApplicationStatus.withdrawn
    await db.commit()
    await db.refresh(app)
    return app


async def get_workflow_logs(db: AsyncSession, application_id: int) -> list[WorkflowLog]:
    result = await db.execute(
        select(WorkflowLog)
        .where(WorkflowLog.application_id == application_id)
        .order_by(WorkflowLog.created_at)
    )
    return result.scalars().all()
