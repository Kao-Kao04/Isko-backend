import re
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import List
from app.models.scholarship import ScholarshipStatus

_TAG_RE = re.compile(r"<[^>]+>")

def _strip_html(v: str | None) -> str | None:
    if v is None:
        return v
    return _TAG_RE.sub("", v).strip()

def _safe_url(v: str | None) -> str | None:
    if v is None:
        return v
    if not v.startswith(("https://", "http://")):
        return None
    # Block internal/localhost URLs to prevent SSRF
    blocked = ("localhost", "127.", "0.0.0.0", "169.254.", "10.", "192.168.", "::1")
    if any(b in v.lower() for b in blocked):
        return None
    return v


class RequirementCreate(BaseModel):
    name: str
    description: str | None = None
    is_required: bool = True


class RequirementResponse(BaseModel):
    id: int
    name: str
    description: str | None
    is_required: bool

    model_config = {"from_attributes": True}


class ScholarshipCreate(BaseModel):
    name: str
    description: str | None = None
    slots: int | None = None
    deadline: datetime | None = None
    eligible_colleges: List[str] | None = None
    eligible_programs: List[str] | None = None
    eligible_year_levels: List[int] | None = None
    min_gwa: str | None = None
    amount_raw: int | None = None
    period: str | None = None
    scholarship_type: str | None = None
    eligibility_text: str | None = None
    cover_image_url: str | None = None
    category: str | None = None
    max_semesters: int | None = None
    requires_thank_you_letter: bool = False
    requirements: List[RequirementCreate] = []

    @field_validator("name", "scholarship_type", "period", mode="before")
    @classmethod
    def sanitize_text(cls, v):           return _strip_html(v)

    @field_validator("description", "eligibility_text", mode="before")
    @classmethod
    def sanitize_long_text(cls, v):      return _strip_html(v)

    @field_validator("cover_image_url", mode="before")
    @classmethod
    def validate_url(cls, v):            return _safe_url(v)


class ScholarshipUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    slots: int | None = None
    deadline: datetime | None = None
    eligible_colleges: List[str] | None = None
    eligible_programs: List[str] | None = None
    eligible_year_levels: List[int] | None = None
    min_gwa: str | None = None
    amount_raw: int | None = None
    period: str | None = None
    scholarship_type: str | None = None
    eligibility_text: str | None = None
    cover_image_url: str | None = None
    category: str | None = None
    max_semesters: int | None = None
    requires_thank_you_letter: bool | None = None
    requirements: List[RequirementCreate] | None = None

    @field_validator("name", "scholarship_type", "period", mode="before")
    @classmethod
    def sanitize_text(cls, v):           return _strip_html(v)

    @field_validator("description", "eligibility_text", mode="before")
    @classmethod
    def sanitize_long_text(cls, v):      return _strip_html(v)

    @field_validator("cover_image_url", mode="before")
    @classmethod
    def validate_url(cls, v):            return _safe_url(v)


class ScholarshipStatusUpdate(BaseModel):
    status: ScholarshipStatus


class ScholarshipResponse(BaseModel):
    id: int
    name: str
    description: str | None
    slots: int | None
    deadline: datetime | None
    status: ScholarshipStatus
    eligible_colleges: List[str] | None
    eligible_programs: List[str] | None
    eligible_year_levels: List[int] | None
    min_gwa: str | None
    amount_raw: int | None
    period: str | None
    scholarship_type: str | None
    eligibility_text: str | None
    cover_image_url: str | None
    category: str | None
    max_semesters: int | None
    requires_thank_you_letter: bool
    applicants_count: int = 0
    requirements: List[RequirementResponse] = []
    created_at: datetime

    model_config = {"from_attributes": True}
