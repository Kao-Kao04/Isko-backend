from pydantic import BaseModel
from datetime import datetime
from typing import List
from app.models.scholar import ScholarStatus


class SemesterRecordCreate(BaseModel):
    semester: str
    academic_year: str
    gwa: str | None = None
    has_grade_below_2_5: bool = False
    is_enrolled: bool = True
    notes: str | None = None


class SemesterRecordUpdate(BaseModel):
    gwa: str | None = None
    has_grade_below_2_5: bool | None = None
    is_enrolled: bool | None = None
    notes: str | None = None


class SemesterRecordResponse(BaseModel):
    id: int
    semester: str
    academic_year: str
    gwa: str | None
    has_grade_below_2_5: bool
    is_enrolled: bool
    notes: str | None
    benefit_released: bool
    benefit_released_at: datetime | None
    thank_you_submitted: bool
    thank_you_submitted_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScholarStatusLogResponse(BaseModel):
    id: int
    from_status: ScholarStatus | None
    to_status: ScholarStatus
    actor_id: int | None
    reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class ScholarStatusUpdate(BaseModel):
    status: ScholarStatus
    is_graduating: bool | None = None
    expected_graduation: str | None = None
    reason: str | None = None


class ScholarResponse(BaseModel):
    id: int
    application_id: int
    student_id: int
    scholarship_id: int
    status: ScholarStatus
    is_graduating: bool
    expected_graduation: str | None
    created_at: datetime
    semester_records: List[SemesterRecordResponse] = []
    status_logs: List[ScholarStatusLogResponse] = []

    model_config = {"from_attributes": True}
