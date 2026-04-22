from pydantic import BaseModel, EmailStr


class InitiateRegisterRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    token: str
    student_number: str
    first_name: str
    last_name: str
    middle_name: str | None = None
    college: str
    program: str
    year_level: int


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
