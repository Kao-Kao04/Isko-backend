from pydantic import BaseModel, EmailStr
from typing import Optional


class StaffCreate(BaseModel):
    email: EmailStr
    password: str
    department: str


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
