from pydantic import BaseModel
from datetime import datetime
from app.models.user import UserRole, AccountStatus


class StudentProfileResponse(BaseModel):
    id: int
    student_number: str
    first_name: str
    last_name: str
    middle_name: str | None
    college: str
    program: str
    year_level: int
    gwa: str | None
    # Address
    street_barangay:   str | None = None
    city_municipality: str | None = None
    province:          str | None = None
    zip_code:          str | None = None
    # Parents
    father_name:       str | None = None
    father_occupation: str | None = None
    mother_name:       str | None = None
    mother_occupation: str | None = None
    # Family income
    income_source:     str | None = None
    monthly_income:    str | None = None

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    id: int
    email: str
    role: UserRole
    is_active: bool
    is_verified: bool
    account_status: AccountStatus
    rejection_remarks: str | None = None
    department: str | None = None
    created_at: datetime
    student_profile: StudentProfileResponse | None = None

    model_config = {"from_attributes": True}


class UpdateProfileRequest(BaseModel):
    gwa: str | None = None
