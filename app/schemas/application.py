from pydantic import BaseModel, model_validator
from datetime import datetime
from typing import Any, List
from app.models.application import ApplicationStatus, EvalStatus


class ApplicationCreate(BaseModel):
    scholarship_id: int


class ApplicationResubmit(BaseModel):
    remarks: str | None = None


class ApplicationStatusUpdate(BaseModel):
    status: ApplicationStatus
    remarks: str | None = None
    rejected_docs: List[int] | None = None


class EvalStatusUpdate(BaseModel):
    eval_status: EvalStatus


class EvalScoreUpdate(BaseModel):
    financial_need: int
    essay: int
    interview: int
    community: int


class AppealCreate(BaseModel):
    reason: str


class AppealReview(BaseModel):
    approved: bool
    review_note: str | None = None


class AuditEntryResponse(BaseModel):
    id: int
    actor_id: int
    action: str
    from_status: str | None
    to_status: str | None
    note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AppealResponse(BaseModel):
    id: int
    reason: str
    status: str
    review_note: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ApplicationStudentInfo(BaseModel):
    id: int
    email: str
    first_name: str | None = None
    last_name: str | None = None
    student_number: str | None = None
    college: str | None = None
    program: str | None = None
    year_level: int | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode='before')
    @classmethod
    def extract_profile(cls, data: Any) -> Any:
        if hasattr(data, 'student_profile') and data.student_profile:
            p = data.student_profile
            return {
                'id':             data.id,
                'email':          data.email,
                'first_name':     p.first_name,
                'last_name':      p.last_name,
                'student_number': p.student_number,
                'college':        p.college,
                'program':        p.program,
                'year_level':     p.year_level,
            }
        return data


class ApplicationScholarshipInfo(BaseModel):
    id: int
    name: str
    scholarship_type: str | None = None

    model_config = {"from_attributes": True}


class ApplicationResponse(BaseModel):
    id: int
    student_id: int
    scholarship_id: int
    status: ApplicationStatus
    eval_status: EvalStatus
    rejected_docs: List[int] | None
    eval_score: dict | None = None
    remarks: str | None
    submitted_at: datetime
    updated_at: datetime
    appeal: AppealResponse | None = None
    student: ApplicationStudentInfo | None = None
    scholarship: ApplicationScholarshipInfo | None = None

    model_config = {"from_attributes": True}
