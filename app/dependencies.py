import hashlib
from fastapi import Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from jose import JWTError

from app.database import get_db
from app.models.user import User, UserRole, AccountStatus
from app.utils.security import decode_token
from app.exceptions import UnauthorizedError, ForbiddenError
from app.token_blacklist import is_revoked

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    # Accept token from Authorization header OR HttpOnly access_token cookie
    token = credentials.credentials if credentials else request.cookies.get("access_token")
    if not token:
        raise UnauthorizedError()
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise UnauthorizedError("Invalid token type")
        user_id: int = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise UnauthorizedError("Invalid or expired token")

    if is_revoked(hashlib.sha256(token.encode()).hexdigest()):
        raise UnauthorizedError("Token has been revoked")

    result = await db.execute(
        select(User)
        .options(selectinload(User.student_profile))
        .where(User.id == user_id, User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise UnauthorizedError("User not found or inactive")
    return user


async def require_student(current_user: User = Depends(get_current_user)) -> User:
    """Email-verified student. Can log in and view dashboard/profile."""
    if current_user.role != UserRole.student:
        raise ForbiddenError("Students only")
    return current_user


async def require_verified_student(current_user: User = Depends(get_current_user)) -> User:
    """OSFA-approved student. Can apply for scholarships and access all features."""
    if current_user.role != UserRole.student:
        raise ForbiddenError("Students only")
    if current_user.account_status != AccountStatus.verified:
        raise ForbiddenError(
            "Your account must be verified by OSFA before you can access this feature"
        )
    return current_user


async def require_osfa(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.osfa_staff:
        raise ForbiddenError("OSFA staff only")
    return current_user


async def require_osfa_or_admin(current_user: User = Depends(get_current_user)) -> User:
    """OSFA staff or super admin — both can manage scholarships and applications."""
    if current_user.role not in (UserRole.osfa_staff, UserRole.super_admin):
        raise ForbiddenError("OSFA staff or super admin access required")
    return current_user


async def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.super_admin:
        raise ForbiddenError("Super admin access required")
    return current_user
