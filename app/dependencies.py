from fastapi import Depends, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from jose import JWTError

from app.database import get_db
from app.models.user import User, UserRole
from app.utils.security import decode_token
from app.exceptions import UnauthorizedError, ForbiddenError

bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise UnauthorizedError()
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise UnauthorizedError("Invalid token type")
        user_id: int = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise UnauthorizedError("Invalid or expired token")

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
    if current_user.role != UserRole.student:
        raise ForbiddenError("Students only")
    return current_user


async def require_osfa(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.osfa_staff:
        raise ForbiddenError("OSFA staff only")
    return current_user
