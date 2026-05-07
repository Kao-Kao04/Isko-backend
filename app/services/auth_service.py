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
RESET_COOLDOWN_SECONDS = 60  # 1 minute per email

logger = logging.getLogger(__name__)

# TTLCache auto-evicts entries after RESET_COOLDOWN_SECONDS — no memory leak
from cachetools import TTLCache
_reset_cooldowns: TTLCache = TTLCache(maxsize=10_000, ttl=RESET_COOLDOWN_SECONDS)


def _check_email_cooldown(email: str) -> None:
    if email in _reset_cooldowns:
        # TTL hasn't expired yet — entry still present means cooldown active
        from app.exceptions import ValidationError as VE
        raise VE(f"Please wait {RESET_COOLDOWN_SECONDS} seconds before requesting another reset link.")
    _reset_cooldowns[email] = True


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
    from app.utils.storage import get_supabase
    sb = get_supabase()
    try:
        sb.auth.sign_up({
            "email": data.email,
            "password": data.password,
            "options": {
                "email_redirect_to": f"{settings.BACKEND_URL}/api/auth/verify-email",
            },
        })
    except Exception as exc:
        logger.error("Supabase sign_up failed for %s: %s", data.email, exc)
        raise RuntimeError("Could not send verification email. Please try again.") from exc

    # hashed_password column is NOT NULL — store a random placeholder.
    # Supabase is the authority for passwords in production.
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
    if not user:
        raise UnauthorizedError("Invalid credentials")

    # Try bcrypt first (existing users whose passwords are stored locally).
    # Fall back to Supabase for users created via the new signup flow.
    if verify_password(data.password, user.hashed_password):
        pass  # bcrypt match — existing user, login OK
    elif settings.ENVIRONMENT != "development":
        from app.utils.storage import get_supabase
        sb = get_supabase()
        try:
            sb.auth.sign_in_with_password({"email": data.email, "password": data.password})
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

    # Re-validate that the user still exists and is active
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
        return  # Silent — don't reveal if email exists

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
    from app.utils.storage import get_supabase
    sb = get_supabase()

    # Ensure the user exists in Supabase Auth. Existing users who signed up
    # before the Supabase migration only live in our DB — create them on demand
    # with a random password so Supabase can send the reset email.
    try:
        sb.auth.admin.create_user({
            "email": email,
            "password": secrets.token_urlsafe(32),
            "email_confirm": True,
        })
        logger.info("Auto-created Supabase Auth user for existing account: %s", email)
    except Exception:
        pass  # Already exists in Supabase Auth — that's fine

    try:
        sb.auth.reset_password_for_email(
            email,
            {"redirect_to": f"{settings.FRONTEND_URL}/reset-password"},
        )
    except Exception as exc:
        logger.error("Supabase reset_password_for_email failed for %s: %s", email, exc)


async def handle_reset_callback(code: str) -> str | None:
    """Exchange Supabase reset code, return our short-lived reset JWT containing the Supabase UID."""
    from datetime import timedelta
    from jose import jwt
    from app.utils.storage import get_supabase
    sb = get_supabase()
    try:
        response = sb.auth.exchange_code_for_session({"auth_code": code})
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

    from app.utils.storage import get_supabase
    sb = get_supabase()
    try:
        sb.auth.admin.update_user_by_id(supabase_uid, {"password": new_password})
    except Exception as exc:
        logger.error("Supabase admin update_user failed for uid %s: %s", supabase_uid, exc)
        raise ValidationError("Could not update password. Please request a new reset link.")


async def verify_email_with_token(db: AsyncSession, access_token: str) -> str | None:
    """Verify email using the Supabase access_token from the implicit flow hash fragment."""
    from app.utils.storage import get_supabase
    sb = get_supabase()
    try:
        user_response = sb.auth.get_user(access_token)
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


async def reset_password_with_supabase_token(access_token: str, new_password: str) -> None:
    """Reset password using the Supabase access_token from the email link hash."""
    from app.utils.storage import get_supabase
    sb = get_supabase()
    try:
        user_response = sb.auth.get_user(access_token)
        supabase_uid = str(user_response.user.id)
    except Exception as exc:
        logger.warning("Invalid Supabase access_token for password reset: %s", exc)
        raise ValidationError("Reset link has expired or is invalid. Please request a new one.")

    try:
        sb.auth.admin.update_user_by_id(supabase_uid, {"password": new_password})
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

    from app.utils.storage import get_supabase
    sb = get_supabase()
    try:
        sb_response = sb.auth.sign_in_with_password({"email": current_user.email, "password": current_password})
        supabase_uid = str(sb_response.user.id)
    except Exception:
        raise ValidationError("Current password is incorrect")

    try:
        sb.auth.admin.update_user_by_id(supabase_uid, {"password": new_password})
    except Exception as exc:
        logger.error("Supabase admin update_user failed for %s: %s", current_user.email, exc)
        raise ValidationError("Could not update password. Please try again.")
