from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, field_validator
from app.models.academic_period import SemesterType, GwaSubmissionStatus


class AcademicPeriodCreate(BaseModel):
    academic_year: str          # "2025-2026"
    semester: SemesterType
    start_date: date
    end_date: date
    counts_toward_max: bool = True

    @field_validator("academic_year")
    @classmethod
    def validate_year(cls, v: str) -> str:
        parts = v.split("-")
        if len(parts) != 2 or not all(p.isdigit() and len(p) == 4 for p in parts):
            raise ValueError("academic_year must be in format YYYY-YYYY (e.g. 2025-2026)")
        return v

    @field_validator("end_date")
    @classmethod
    def end_after_start(cls, v: date, info) -> date:
        start = info.data.get("start_date")
        if start and v <= start:
            raise ValueError("end_date must be after start_date")
        return v


class AcademicPeriodResponse(BaseModel):
    id: int
    academic_year: str
    semester: SemesterType
    start_date: date
    end_date: date
    counts_toward_max: bool
    is_active: bool
    is_ended: bool
    label: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── GWA Submission schemas ────────────────────────────────────────────────────

class GwaSubmissionResponse(BaseModel):
    id: int
    scholar_id: int
    period_id: int
    declared_gwa: Optional[str]
    has_grade_below_2_5: bool
    status: GwaSubmissionStatus
    rejection_remarks: Optional[str]
    submitted_at: datetime
    reviewed_at: Optional[datetime]
    period: AcademicPeriodResponse
    proof_url: Optional[str] = None  # populated by router via get_signed_url

    model_config = {"from_attributes": True}


class GwaSubmissionReview(BaseModel):
    confirmed_gwa: Optional[str] = None        # OSFA-confirmed GWA (may differ from declared)
    has_grade_below_2_5: Optional[bool] = None
    notes: Optional[str] = None


class GwaSubmissionReject(BaseModel):
    remarks: str
