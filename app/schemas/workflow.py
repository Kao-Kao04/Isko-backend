from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Any
from app.models.workflow import MainStatus, SubStatus


# ── Requests ─────────────────────────────────────────────────────────────────

class ScreeningResultRequest(BaseModel):
    passed: bool
    note: str | None = None


class VerificationResultRequest(BaseModel):
    passed: bool
    note: str | None = None


class RevisionRequest(BaseModel):
    note: str


class ScheduleInterviewRequest(BaseModel):
    interview_datetime: datetime
    location: str | None = None
    note: str | None = None


class RescheduleInterviewRequest(BaseModel):
    reason: str | None = None


class CompleteInterviewRequest(BaseModel):
    notes: str | None = None


class EvaluationRequest(BaseModel):
    eval_score: dict[str, Any] | None = None
    note: str | None = None


class DecisionRequest(BaseModel):
    decision: str   # "approved" | "rejected" | "waitlisted"
    remarks: str | None = None

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, v: str) -> str:
        if v not in ("approved", "rejected", "waitlisted"):
            raise ValueError("decision must be: approved, rejected, or waitlisted")
        return v


class CompletionRequirementItem(BaseModel):
    requirement_type: str
    file_url: str | None = None


class SubmitCompletionRequest(BaseModel):
    requirements: list[CompletionRequirementItem]


class WithdrawRequest(BaseModel):
    reason: str | None = None


class FinalizeRequest(BaseModel):
    note: str | None = None


# ── Responses ────────────────────────────────────────────────────────────────

class WorkflowLogResponse(BaseModel):
    id: int
    from_main: MainStatus | None
    from_sub: SubStatus | None
    to_main: MainStatus
    to_sub: SubStatus
    note: str | None
    changed_by: int
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkflowStatusResponse(BaseModel):
    application_id: int
    main_status: MainStatus | None
    sub_status: SubStatus | None
    submitted_at: datetime | None
    screened_at: datetime | None
    validated_at: datetime | None
    interview_scheduled_at: datetime | None
    interview_datetime: datetime | None
    interview_completed_at: datetime | None
    evaluated_at: datetime | None
    decision_released_at: datetime | None
    completion_submitted_at: datetime | None
    closed_at: datetime | None
    interview_location: str | None
    decision_remarks: str | None
    logs: list[WorkflowLogResponse] = []

    model_config = {"from_attributes": True}
