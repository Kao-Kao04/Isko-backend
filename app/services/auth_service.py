from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from jose import JWTError

from app.models.user import User, UserRole, AccountStatus, StudentProfile
from app.schemas.auth import InitiateRegisterRequest, RegisterRequest, LoginRequest
from app.utils.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
    create_email_verification_token, decode_registration_token,
)
from app.utils.email import send_verification_email
from app.exceptions import ConflictError, UnauthorizedError, ValidationError
from app.config import settings


async def initiate_register(db: AsyncSession, data: InitiateRegisterRequest) -> dict:
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise ConflictError("Email already registered")

    hashed = hash_password(data.password)
    token = create_email_verification_token(data.email, hashed)

    if settings.ENVIRONMENT == "development":
        from app.utils.security import create_registration_token
        reg_token = create_registration_token(data.email, hashed)
        return {"dev": True, "token": reg_token}

    send_verification_email(data.email, token)
    return {"dev": False}


async def register_student(db: AsyncSession, data: RegisterRequest) -> User:
    try:
        payload = decode_registration_token(data.token)
    except (JWTError, ValueError):
        raise ValidationError("Invalid or expired registration token")

    email = payload["email"]
    hashed_password = payload["hashed_password"]

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise ConflictError("Email already registered")

    sn_check = await db.execute(
        select(StudentProfile).where(StudentProfile.student_number == data.student_number)
    )
    if sn_check.scalar_one_or_none():
        raise ConflictError("Student number already registered")

    user = User(
        email=email,
        hashed_password=hashed_password,
        role=UserRole.student,
        is_verified=True,
        account_status=AccountStatus.approved,
    )
    db.add(user)
    await db.flush()

    profile = StudentProfile(
        user_id=user.id,
        student_number=data.student_number,
        first_name=data.first_name,
        last_name=data.last_name,
        middle_name=data.middle_name,
        college=data.college,
        program=data.program,
        year_level=data.year_level,
    )
    db.add(profile)
    await db.commit()

    result = await db.execute(
        select(User).options(selectinload(User.student_profile)).where(User.id == user.id)
    )
    return result.scalar_one()


async def login(db: AsyncSession, data: LoginRequest) -> dict:
    result = await db.execute(select(User).where(User.email == data.email, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.hashed_password):
        raise UnauthorizedError("Invalid credentials")
    if not user.is_verified:
        raise UnauthorizedError("Please verify your email before logging in")
    if user.account_status == "pending":
        raise UnauthorizedError("Your account is pending OSFA approval")
    if user.account_status == "rejected":
        raise UnauthorizedError("Your account registration was rejected")

    payload = {"sub": str(user.id), "role": user.role}
    return {
        "access_token": create_access_token(payload),
        "refresh_token": create_refresh_token(payload),
    }


def refresh_tokens(refresh_token: str) -> dict:
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise UnauthorizedError("Invalid token type")
    except JWTError:
        raise UnauthorizedError("Invalid or expired refresh token")

    token_payload = {"sub": payload["sub"], "role": payload["role"]}
    return {
        "access_token": create_access_token(token_payload),
        "refresh_token": create_refresh_token(token_payload),
    }
