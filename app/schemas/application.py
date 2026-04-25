from pydantic import BaseModel
from datetime import datetime
from typing import List
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
    remarks: str | None
    submitted_at: datetime
    updated_at: datetime
    appeal: AppealResponse | None = None
    student: ApplicationStudentInfo | None = None
    scholarship: ApplicationScholarshipInfo | None = None

    model_config = {"from_attributes": True}
