from pydantic import BaseModel, EmailStr, field_validator

ALLOWED_DOMAINS = {"iskolarngbayan.pup.edu.ph", "gmail.com"}


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def email_domain(cls, v: str) -> str:
        domain = v.split("@")[-1].lower()
        if domain not in ALLOWED_DOMAINS:
            raise ValueError(
                "Only @iskolarngbayan.pup.edu.ph and @gmail.com email addresses are allowed."
            )
        return v

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    remember_me: bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
