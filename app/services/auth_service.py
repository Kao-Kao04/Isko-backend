import secrets
import logging

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError

from app.models.user import User, UserRole, AccountStatus
from app.schemas.auth import SignUpRequest, LoginRequest
from app.utils.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token, decode_token,
)
from app.exceptions import ConflictError, UnauthorizedError
from app.config import settings

logger = logging.getLogger(__name__)


async def signup(db: AsyncSession, data: SignUpRequest) -> dict:
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise ConflictError("Email already registered")

    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        role=UserRole.student,
        is_verified=False,
        account_status=AccountStatus.unregistered,
    )
    db.add(user)
    await db.commit()

    if settings.ENVIRONMENT == "development":
        user.is_verified = True
        await db.commit()
        return {"dev": True}

    from app.utils.storage import get_supabase
    sb = get_supabase()
    try:
        sb.auth.sign_up({
            "email": data.email,
            "password": secrets.token_urlsafe(32),
            "options": {
                "email_redirect_to": f"{settings.BACKEND_URL}/api/auth/verify-email",
            },
        })
    except Exception as exc:
        await db.delete(user)
        await db.commit()
        logger.error("Supabase sign_up failed for %s: %s", data.email, exc)
        raise RuntimeError("Could not send verification email. Please try again.") from exc

    return {"dev": False}


async def verify_email_and_activate(db: AsyncSession, code: str) -> str | None:
    """Exchange Supabase code, find our user by email, mark as verified. Returns email."""
    from app.utils.storage import get_supabase
    sb = get_supabase()
    try:
        response = sb.auth.exchange_code_for_session({"auth_code": code})
        email = response.user.email
    except Exception as exc:
        logger.warning("Supabase code exchange failed: %s", exc)
        return None

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        return None

    if not user.is_verified:
        user.is_verified = True
        await db.commit()

    return email


async def login(db: AsyncSession, data: LoginRequest) -> dict:
    result = await db.execute(
        select(User).where(User.email == data.email, User.is_active == True)
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(data.password, user.hashed_password):
        raise UnauthorizedError("Invalid credentials")
    if not user.is_verified:
        raise UnauthorizedError("Please verify your email before logging in")

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
