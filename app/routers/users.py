from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.dependencies import get_current_user, require_osfa
from app.models.user import User, AccountStatus
from app.schemas.user import UserResponse, UpdateProfileRequest
from app.schemas.common import PaginatedResponse
from app.utils.pagination import paginate
from app.exceptions import NotFoundError

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_me(
    data: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = current_user.student_profile
    if profile:
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(profile, field, value)
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.get("", response_model=PaginatedResponse[UserResponse])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    account_status: str | None = Query(None),
    _: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    query = select(User)
    count_query = select(func.count(User.id))

    if account_status:
        query = query.where(User.account_status == account_status)
        count_query = count_query.where(User.account_status == account_status)

    count_result = await db.execute(count_query)
    total = count_result.scalar()
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    users = result.scalars().all()
    return paginate(users, total, page, page_size)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    _: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User", user_id)
    return user


@router.patch("/{user_id}/approve", response_model=UserResponse)
async def approve_student(
    user_id: int,
    _: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User", user_id)
    user.account_status = AccountStatus.approved
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}/reject", response_model=UserResponse)
async def reject_student(
    user_id: int,
    _: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User", user_id)
    user.account_status = AccountStatus.rejected
    await db.commit()
    await db.refresh(user)
    return user
