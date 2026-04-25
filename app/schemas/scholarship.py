from pydantic import BaseModel
from datetime import datetime
from typing import List
from app.models.scholarship import ScholarshipStatus


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
    requirements: List[RequirementCreate] = []


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
    applicants_count: int = 0
    requirements: List[RequirementResponse] = []
    created_at: datetime

    model_config = {"from_attributes": True}
