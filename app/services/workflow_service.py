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
from app.models.user import User
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

    if is_terminal(app.main_status):
        raise ValidationError(
            f"Application is already in a terminal state: {app.main_status}/{app.sub_status}"
        )

    if not can_transition(app.main_status, app.sub_status, to_main, to_sub):
        raise ValidationError(
            f"Invalid transition: {app.main_status}/{app.sub_status} → {to_main}/{to_sub}. "
            f"Allowed: {ALLOWED_TRANSITIONS.get((app.main_status, app.sub_status), [])}"
        )


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
    await db.commit()
    await db.refresh(app)
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
    app = await _apply(db, app, actor, MainStatus.APPLICATION, SubStatus.SCREENING)
    app.screened_at = _now()
    await db.commit()
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
        return await _apply(db, app, actor, MainStatus.APPLICATION, SubStatus.SCREENING_PASSED, note)
    else:
        app = await _apply(db, app, actor, MainStatus.APPLICATION, SubStatus.SCREENING_FAILED, note)
        # Auto-transition to terminal rejected
        return await _apply(db, app, actor, MainStatus.REJECTED, SubStatus.REJECTED, note)


async def start_verification(db: AsyncSession, application_id: int, actor: User) -> Application:
    app = await _get_app(db, application_id)
    return await _apply(db, app, actor, MainStatus.VERIFICATION, SubStatus.PENDING_VALIDATION)


async def request_revision(
    db: AsyncSession, application_id: int, actor: User, note: str
) -> Application:
    app = await _get_app(db, application_id)
    return await _apply(db, app, actor, MainStatus.VERIFICATION, SubStatus.REVISION_REQUESTED, note)


async def complete_verification(
    db: AsyncSession,
    application_id: int,
    actor: User,
    passed: bool,
    note: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    if passed:
        result = await _apply(db, app, actor, MainStatus.VERIFICATION, SubStatus.VALIDATED, note)
        result.validated_at = _now()
        await db.commit()
        return result
    else:
        app = await _apply(db, app, actor, MainStatus.VERIFICATION, SubStatus.VALIDATION_FAILED, note)
        app = await _apply(db, app, actor, MainStatus.REJECTED, SubStatus.REJECTED, note)
        app.closed_at = _now()
        await db.commit()
        return app


async def open_interview_scheduling(db: AsyncSession, application_id: int, actor: User) -> Application:
    """OSFA opens interview scheduling after verification."""
    app = await _get_app(db, application_id)
    return await _apply(db, app, actor, MainStatus.INTERVIEW, SubStatus.NOT_SCHEDULED)


async def schedule_interview(
    db: AsyncSession,
    application_id: int,
    actor: User,
    interview_datetime: datetime,
    location: str | None = None,
    note: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)

    current_sub = app.sub_status
    if current_sub == SubStatus.RESCHEDULED:
        to_sub = SubStatus.SCHEDULED
    elif current_sub == SubStatus.NOT_SCHEDULED:
        to_sub = SubStatus.SCHEDULED
    else:
        raise ValidationError(f"Cannot schedule interview from state {current_sub}")

    app = await _apply(db, app, actor, MainStatus.INTERVIEW, to_sub, note)
    app.interview_datetime = interview_datetime
    app.interview_scheduled_at = _now()
    if location:
        app.interview_location = location
    await db.commit()
    return app


async def reschedule_interview(
    db: AsyncSession,
    application_id: int,
    actor: User,
    reason: str,
) -> Application:
    app = await _get_app(db, application_id)
    if app.sub_status != SubStatus.SCHEDULED:
        raise ValidationError("Can only reschedule a SCHEDULED interview.")
    return await _apply(db, app, actor, MainStatus.INTERVIEW, SubStatus.RESCHEDULED, reason)


async def complete_interview(
    db: AsyncSession,
    application_id: int,
    actor: User,
    notes: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)

    # Guard: must have a scheduled datetime
    if not app.interview_datetime:
        raise ValidationError("Cannot complete interview — no interview schedule exists.")
    if app.sub_status != SubStatus.SCHEDULED:
        raise ValidationError("Interview must be in SCHEDULED state to be completed.")

    app = await _apply(db, app, actor, MainStatus.INTERVIEW, SubStatus.INTERVIEW_COMPLETED, notes)
    app.interview_completed_at = _now()
    if notes:
        app.interview_notes = notes
    await db.commit()
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

    app = await _apply(db, app, actor, MainStatus.INTERVIEW, SubStatus.EVALUATED, note)
    app.evaluated_at = _now()
    if eval_score:
        app.eval_score = eval_score
    await db.commit()
    return app


async def move_to_review(db: AsyncSession, application_id: int, actor: User) -> Application:
    app = await _get_app(db, application_id)
    if app.sub_status != SubStatus.EVALUATED:
        raise ValidationError("Cannot move to review — evaluation not yet submitted.")
    return await _apply(db, app, actor, MainStatus.DECISION, SubStatus.UNDER_REVIEW)


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
    app = await _apply(db, app, actor, MainStatus.DECISION, to_sub, remarks)
    app.decision_released_at = _now()
    if remarks:
        app.decision_remarks = remarks

    if decision == "rejected":
        app.closed_at = _now()

    await db.commit()

    # Auto-progress approved → COMPLETION
    if decision == "approved":
        app = await _apply(db, app, actor, MainStatus.COMPLETION, SubStatus.PENDING_REQUIREMENTS)

    return app


async def submit_completion_requirements(
    db: AsyncSession,
    application_id: int,
    actor: User,
    requirements: list[dict],  # [{"requirement_type": "...", "file_url": "..."}]
) -> Application:
    app = await _get_app(db, application_id)
    if app.sub_status != SubStatus.PENDING_REQUIREMENTS:
        raise ValidationError("Not in PENDING_REQUIREMENTS state.")

    for req in requirements:
        db.add(CompletionRequirement(
            application_id=application_id,
            requirement_type=req["requirement_type"],
            file_url=req.get("file_url"),
            submitted_at=_now(),
        ))

    app = await _apply(db, app, actor, MainStatus.COMPLETION, SubStatus.REQUIREMENTS_SUBMITTED)
    app.completion_submitted_at = _now()
    await db.commit()
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
    app = await _apply(db, app, actor, MainStatus.COMPLETION, SubStatus.COMPLETED, note)
    app.closed_at = _now()
    await db.commit()
    return app


async def withdraw(
    db: AsyncSession,
    application_id: int,
    actor: User,
    reason: str | None = None,
) -> Application:
    app = await _get_app(db, application_id)
    if is_terminal(app.main_status):
        raise ValidationError("Cannot withdraw — application is already in a terminal state.")
    # Withdrawal allowed from any non-terminal state
    await _log(db, app, actor, MainStatus.WITHDRAWN, SubStatus.WITHDRAWN, reason)
    app.main_status = MainStatus.WITHDRAWN
    app.sub_status = SubStatus.WITHDRAWN
    app.closed_at = _now()
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
