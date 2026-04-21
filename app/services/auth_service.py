from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError

from app.models.user import User, UserRole, StudentProfile
from app.schemas.auth import RegisterRequest, LoginRequest
from app.utils.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.exceptions import ConflictError, UnauthorizedError


async def register_student(db: AsyncSession, data: RegisterRequest) -> User:
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise ConflictError("Email already registered")

    sn_check = await db.execute(
        select(StudentProfile).where(StudentProfile.student_number == data.student_number)
    )
    if sn_check.scalar_one_or_none():
        raise ConflictError("Student number already registered")

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        role=UserRole.student,
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
    await db.refresh(user)
    return user


async def login(db: AsyncSession, data: LoginRequest) -> dict:
    result = await db.execute(select(User).where(User.email == data.email, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user or not verify_password(data.password, user.hashed_password):
        raise UnauthorizedError("Invalid credentials")

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
