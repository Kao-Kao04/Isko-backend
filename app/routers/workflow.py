from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.database import get_db
from app.dependencies import get_current_user, require_osfa_or_admin, require_verified_student
from app.models.user import User, UserRole
from app.models.application import Application
from app.schemas.workflow import (
    ScreeningResultRequest, VerificationResultRequest, RevisionRequest,
    ScheduleInterviewRequest, RescheduleInterviewRequest, CompleteInterviewRequest,
    EvaluationRequest, DecisionRequest, SubmitCompletionRequest,
    WithdrawRequest, FinalizeRequest,
    WorkflowStatusResponse, WorkflowLogResponse,
)
from app.services import workflow_service
from app.exceptions import NotFoundError, ForbiddenError

router = APIRouter(prefix="/api/workflow", tags=["workflow"])


async def _get_app_or_404(db: AsyncSession, application_id: int) -> Application:
    result = await db.execute(
        select(Application)
        .options(
            selectinload(Application.workflow_logs),
            selectinload(Application.completion_requirements),
        )
        .where(Application.id == application_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise NotFoundError("Application", application_id)
    return app


def _assert_can_view(app: Application, user: User) -> None:
    """Students can only view their own application's workflow."""
    if user.role == UserRole.student and app.student_id != user.id:
        raise ForbiddenError("You do not have access to this application")


# ── Status & Logs ─────────────────────────────────────────────────────────────

@router.get("/{application_id}", response_model=WorkflowStatusResponse)
async def get_workflow_status(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await _get_app_or_404(db, application_id)
    _assert_can_view(app, current_user)
    return WorkflowStatusResponse(
        application_id=app.id,
        main_status=app.main_status,
        sub_status=app.sub_status,
        submitted_at=app.submitted_at,
        screened_at=app.screened_at,
        validated_at=app.validated_at,
        interview_scheduled_at=app.interview_scheduled_at,
        interview_datetime=app.interview_datetime,
        interview_completed_at=app.interview_completed_at,
        evaluated_at=app.evaluated_at,
        decision_released_at=app.decision_released_at,
        completion_submitted_at=app.completion_submitted_at,
        closed_at=app.closed_at,
        interview_location=app.interview_location,
        decision_remarks=app.decision_remarks,
        logs=[WorkflowLogResponse.model_validate(log) for log in app.workflow_logs],
    )


@router.get("/{application_id}/logs", response_model=list[WorkflowLogResponse])
async def get_logs(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await _get_app_or_404(db, application_id)
    _assert_can_view(app, current_user)
    logs = await workflow_service.get_workflow_logs(db, application_id)
    return [WorkflowLogResponse.model_validate(log) for log in logs]


# ── APPLICATION stage ─────────────────────────────────────────────────────────

@router.post("/{application_id}/initialize", status_code=200)
async def initialize(
    application_id: int,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Initialize workflow for an existing application (OSFA/admin action)."""
    app = await workflow_service.initialize_workflow(db, application_id, current_user)
    return {"main_status": app.main_status, "sub_status": app.sub_status}


@router.post("/{application_id}/screen", status_code=200)
async def start_screening(
    application_id: int,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.start_screening(db, application_id, current_user)
    return {"main_status": app.main_status, "sub_status": app.sub_status}


@router.post("/{application_id}/screening-result", status_code=200)
async def screening_result(
    application_id: int,
    data: ScreeningResultRequest,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.complete_screening(db, application_id, current_user, data.passed, data.note)
    return {"main_status": app.main_status, "sub_status": app.sub_status}


# ── VERIFICATION stage ────────────────────────────────────────────────────────

@router.post("/{application_id}/start-verification", status_code=200)
async def start_verification(
    application_id: int,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.start_verification(db, application_id, current_user)
    return {"main_status": app.main_status, "sub_status": app.sub_status}


@router.post("/{application_id}/request-revision", status_code=200)
async def request_revision(
    application_id: int,
    data: RevisionRequest,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.request_revision(db, application_id, current_user, data.note)
    return {"main_status": app.main_status, "sub_status": app.sub_status}


@router.post("/{application_id}/verification-result", status_code=200)
async def verification_result(
    application_id: int,
    data: VerificationResultRequest,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.complete_verification(db, application_id, current_user, data.passed, data.note)
    return {"main_status": app.main_status, "sub_status": app.sub_status}


# ── INTERVIEW stage ───────────────────────────────────────────────────────────

@router.post("/{application_id}/open-scheduling", status_code=200)
async def open_scheduling(
    application_id: int,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.open_interview_scheduling(db, application_id, current_user)
    return {"main_status": app.main_status, "sub_status": app.sub_status}


@router.post("/{application_id}/schedule-interview", status_code=200)
async def schedule_interview(
    application_id: int,
    data: ScheduleInterviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Student or OSFA/admin can schedule the interview."""
    app = await workflow_service.schedule_interview(
        db, application_id, current_user,
        data.interview_datetime, data.location, data.note,
    )
    return {
        "main_status": app.main_status,
        "sub_status": app.sub_status,
        "interview_datetime": app.interview_datetime,
        "interview_location": app.interview_location,
    }


@router.post("/{application_id}/reschedule-interview", status_code=200)
async def reschedule_interview(
    application_id: int,
    data: RescheduleInterviewRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.reschedule_interview(db, application_id, current_user, data.reason)
    return {"main_status": app.main_status, "sub_status": app.sub_status}


@router.post("/{application_id}/complete-interview", status_code=200)
async def complete_interview(
    application_id: int,
    data: CompleteInterviewRequest,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.complete_interview(db, application_id, current_user, data.notes)
    return {"main_status": app.main_status, "sub_status": app.sub_status}


@router.post("/{application_id}/evaluate", status_code=200)
async def evaluate(
    application_id: int,
    data: EvaluationRequest,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.submit_evaluation(db, application_id, current_user, data.eval_score, data.note)
    return {"main_status": app.main_status, "sub_status": app.sub_status, "evaluated_at": app.evaluated_at}


@router.post("/{application_id}/move-to-review", status_code=200)
async def move_to_review(
    application_id: int,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.move_to_review(db, application_id, current_user)
    return {"main_status": app.main_status, "sub_status": app.sub_status}


# ── DECISION stage ────────────────────────────────────────────────────────────

@router.post("/{application_id}/decide", status_code=200)
async def decide(
    application_id: int,
    data: DecisionRequest,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.release_decision(
        db, application_id, current_user, data.decision, data.remarks
    )
    return {
        "main_status": app.main_status,
        "sub_status": app.sub_status,
        "decision_released_at": app.decision_released_at,
    }


# ── COMPLETION stage ──────────────────────────────────────────────────────────

@router.post("/{application_id}/submit-requirements", status_code=200)
async def submit_requirements(
    application_id: int,
    data: SubmitCompletionRequest,
    current_user: User = Depends(require_verified_student),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.submit_completion_requirements(
        db, application_id, current_user,
        [r.model_dump() for r in data.requirements],
    )
    return {"main_status": app.main_status, "sub_status": app.sub_status}


@router.post("/{application_id}/finalize", status_code=200)
async def finalize(
    application_id: int,
    data: FinalizeRequest,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.finalize(db, application_id, current_user, data.note)
    return {"main_status": app.main_status, "sub_status": app.sub_status, "closed_at": app.closed_at}


# ── Withdraw (any stage) ──────────────────────────────────────────────────────

@router.post("/{application_id}/withdraw", status_code=200)
async def withdraw(
    application_id: int,
    data: WithdrawRequest,
    current_user: User = Depends(require_verified_student),
    db: AsyncSession = Depends(get_db),
):
    app = await workflow_service.withdraw(db, application_id, current_user, data.reason)
    return {"main_status": app.main_status, "sub_status": app.sub_status, "closed_at": app.closed_at}
