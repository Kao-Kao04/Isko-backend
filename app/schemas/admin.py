from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional


class StaffCreate(BaseModel):
    email: EmailStr
    password: str
    department: str

    @field_validator("password")
    @classmethod
    def password_min(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class StaffUpdate(BaseModel):
    department: Optional[str] = None
    is_active: Optional[bool] = None


class StaffResponse(BaseModel):
    id: int
    email: str
    department: Optional[str]
    is_active: bool
    created_at: str

    model_config = {"from_attributes": True}
