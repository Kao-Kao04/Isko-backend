import asyncio
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
from app.exceptions import ConflictError, UnauthorizedError, ValidationError
from app.config import settings

RESET_TOKEN_EXPIRE_MINUTES = 30
RESET_COOLDOWN_SECONDS = 60

logger = logging.getLogger(__name__)

from cachetools import TTLCache
_reset_cooldowns: TTLCache = TTLCache(maxsize=10_000, ttl=RESET_COOLDOWN_SECONDS)


def _check_email_cooldown(email: str) -> None:
    if email in _reset_cooldowns:
        raise ValidationError(f"Please wait {RESET_COOLDOWN_SECONDS} seconds before requesting another reset link.")
    _reset_cooldowns[email] = True


def _sb():
    from app.utils.storage import get_supabase
    return get_supabase()


async def signup(db: AsyncSession, data: SignUpRequest) -> dict:
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise ConflictError("Email already registered")

    if settings.ENVIRONMENT == "development":
        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            role=UserRole.student,
            is_verified=True,
            account_status=AccountStatus.unregistered,
        )
        db.add(user)
        await db.commit()
        return {"dev": True}

    import secrets
    try:
        await asyncio.to_thread(_sb().auth.sign_up, {
            "email": data.email,
            "password": data.password,
            "options": {"email_redirect_to": f"{settings.FRONTEND_URL}/verify-email"},
        })
    except Exception as exc:
        logger.error("Supabase sign_up failed for %s: %s", data.email, exc)
        raise RuntimeError("Could not send verification email. Please try again.") from exc

    user = User(
        email=data.email,
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        role=UserRole.student,
        is_verified=False,
        account_status=AccountStatus.unregistered,
    )
    db.add(user)
    await db.commit()
    return {"dev": False}


async def verify_email_and_activate(db: AsyncSession, code: str) -> str | None:
    try:
        response = await asyncio.to_thread(
            _sb().auth.exchange_code_for_session, {"auth_code": code}
        )
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


async def verify_email_with_token(db: AsyncSession, access_token: str) -> str | None:
    """Verify email using the Supabase access_token from the implicit flow hash fragment."""
    try:
        user_response = await asyncio.to_thread(_sb().auth.get_user, access_token)
        email = user_response.user.email
    except Exception as exc:
        logger.warning("Invalid Supabase access_token for email verification: %s", exc)
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
    if not user:
        raise UnauthorizedError("Invalid credentials")

    if verify_password(data.password, user.hashed_password):
        pass
    elif settings.ENVIRONMENT != "development":
        try:
            await asyncio.to_thread(
                _sb().auth.sign_in_with_password,
                {"email": data.email, "password": data.password},
            )
        except Exception:
            raise UnauthorizedError("Invalid credentials")
    else:
        raise UnauthorizedError("Invalid credentials")

    if not user.is_verified:
        raise UnauthorizedError("Please verify your email before logging in")

    payload = {"sub": str(user.id), "role": user.role}
    return {
        "access_token": create_access_token(payload),
        "refresh_token": create_refresh_token(payload),
    }


async def refresh_tokens(db: AsyncSession, refresh_token: str) -> dict:
    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise UnauthorizedError("Invalid token type")
    except JWTError:
        raise UnauthorizedError("Invalid or expired refresh token")

    user_id = int(payload["sub"])
    result = await db.execute(
        select(User).where(User.id == user_id, User.is_active == True)
    )
    if not result.scalar_one_or_none():
        raise UnauthorizedError("User not found or account has been deactivated")

    token_payload = {"sub": payload["sub"], "role": payload["role"]}
    return {
        "access_token": create_access_token(token_payload),
        "refresh_token": create_refresh_token(token_payload),
    }


async def send_password_reset(db: AsyncSession, email: str) -> None:
    _check_email_cooldown(email)

    result = await db.execute(
        select(User).where(User.email == email, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        return

    if settings.ENVIRONMENT == "development":
        from datetime import timedelta
        from jose import jwt
        token = jwt.encode(
            {
                "sub": str(user.id),
                "type": "password_reset",
                "exp": __import__("datetime").datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
            },
            settings.SECRET_KEY,
            algorithm=settings.ALGORITHM,
        )
        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        logger.info("DEV — password reset link for %s: %s", email, reset_url)
        return

    import secrets
    try:
        await asyncio.to_thread(_sb().auth.admin.create_user, {
            "email": email,
            "password": secrets.token_urlsafe(32),
            "email_confirm": True,
        })
        logger.info("Auto-created Supabase Auth user for existing account: %s", email)
    except Exception:
        pass

    try:
        await asyncio.to_thread(
            _sb().auth.reset_password_for_email,
            email,
            {"redirect_to": f"{settings.FRONTEND_URL}/reset-password"},
        )
    except Exception as exc:
        logger.error("Supabase reset_password_for_email failed for %s: %s", email, exc)


async def handle_reset_callback(code: str) -> str | None:
    from datetime import timedelta
    from jose import jwt
    try:
        response = await asyncio.to_thread(
            _sb().auth.exchange_code_for_session, {"auth_code": code}
        )
        supabase_uid = str(response.user.id)
    except Exception as exc:
        logger.warning("Supabase reset code exchange failed: %s", exc)
        return None

    token = jwt.encode(
        {
            "supabase_uid": supabase_uid,
            "type": "password_reset",
            "exp": __import__("datetime").datetime.utcnow() + timedelta(minutes=RESET_TOKEN_EXPIRE_MINUTES),
        },
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )
    return token


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    from jose import jwt, JWTError as JoseJWTError
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != "password_reset":
            raise ValidationError("Invalid reset token")
    except JoseJWTError:
        raise ValidationError("Reset link has expired or is invalid. Please request a new one.")

    if settings.ENVIRONMENT == "development":
        user_id = int(payload["sub"])
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise ValidationError("User not found")
        user.hashed_password = hash_password(new_password)
        await db.commit()
        return

    supabase_uid = payload.get("supabase_uid")
    if not supabase_uid:
        raise ValidationError("Invalid reset token")

    try:
        await asyncio.to_thread(
            _sb().auth.admin.update_user_by_id, supabase_uid, {"password": new_password}
        )
    except Exception as exc:
        logger.error("Supabase admin update_user failed for uid %s: %s", supabase_uid, exc)
        raise ValidationError("Could not update password. Please request a new reset link.")


async def reset_password_with_supabase_token(access_token: str, new_password: str) -> None:
    try:
        user_response = await asyncio.to_thread(_sb().auth.get_user, access_token)
        supabase_uid = str(user_response.user.id)
    except Exception as exc:
        logger.warning("Invalid Supabase access_token for password reset: %s", exc)
        raise ValidationError("Reset link has expired or is invalid. Please request a new one.")

    try:
        await asyncio.to_thread(
            _sb().auth.admin.update_user_by_id, supabase_uid, {"password": new_password}
        )
    except Exception as exc:
        logger.error("Supabase admin update_user failed for uid %s: %s", supabase_uid, exc)
        raise ValidationError("Could not update password. Please request a new reset link.")


async def change_password(db: AsyncSession, current_user: User, current_password: str, new_password: str) -> None:
    if settings.ENVIRONMENT == "development":
        if not verify_password(current_password, current_user.hashed_password):
            raise ValidationError("Current password is incorrect")
        current_user.hashed_password = hash_password(new_password)
        await db.commit()
        return

    try:
        sb_response = await asyncio.to_thread(
            _sb().auth.sign_in_with_password,
            {"email": current_user.email, "password": current_password},
        )
        supabase_uid = str(sb_response.user.id)
    except Exception:
        raise ValidationError("Current password is incorrect")

    try:
        await asyncio.to_thread(
            _sb().auth.admin.update_user_by_id, supabase_uid, {"password": new_password}
        )
    except Exception as exc:
        logger.error("Supabase admin update_user failed for %s: %s", current_user.email, exc)
        raise ValidationError("Could not update password. Please try again.")
