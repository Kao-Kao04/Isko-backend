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

    model_config = {"from_attributes": True}


class UserResponse(BaseModel):
    id: int
    email: str
    role: UserRole
    is_active: bool
    is_verified: bool
    account_status: AccountStatus
    department: str | None = None
    created_at: datetime
    student_profile: StudentProfileResponse | None = None

    model_config = {"from_attributes": True}


class UpdateProfileRequest(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    middle_name: str | None = None
    college: str | None = None
    program: str | None = None
    year_level: int | None = None
    gwa: str | None = None
