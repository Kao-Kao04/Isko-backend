from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.dependencies import require_osfa, require_student
from app.models.user import User, UserRole, AccountStatus
from app.models.registration import RegistrationDocument
from app.schemas.user import UserResponse, UpdateProfileRequest
from app.schemas.common import PaginatedResponse
from app.utils.pagination import paginate
from app.utils.storage import get_public_url
from app.exceptions import NotFoundError, ValidationError

router = APIRouter(prefix="/api/users", tags=["users"])


class RejectStudentRequest(BaseModel):
    remarks: str


@router.put("/me", response_model=UserResponse)
async def update_me(
    data: UpdateProfileRequest,
    current_user: User = Depends(require_student),
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
    query = select(User).where(User.role == UserRole.student)
    count_query = select(func.count(User.id)).where(User.role == UserRole.student)

    if account_status:
        query = query.where(User.account_status == account_status)
        count_query = count_query.where(User.account_status == account_status)

    count_result = await db.execute(count_query)
    total = count_result.scalar()
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    users = result.scalars().all()
    return paginate(users, total, page, page_size)


async def _get_student_or_404(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(
        select(User).where(User.id == user_id, User.role == UserRole.student)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User", user_id)
    return user


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    _: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    return await _get_student_or_404(db, user_id)


@router.get("/{user_id}/registration-documents")
async def get_registration_documents(
    user_id: int,
    _: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    await _get_student_or_404(db, user_id)
    result = await db.execute(
        select(RegistrationDocument).where(RegistrationDocument.user_id == user_id)
    )
    docs = result.scalars().all()
    return [
        {
            "id": d.id,
            "doc_type": d.doc_type,
            "filename": d.filename,
            "url": get_public_url(d.storage_path),
            "uploaded_at": d.uploaded_at,
        }
        for d in docs
    ]


@router.patch("/{user_id}/approve", response_model=UserResponse)
async def approve_student(
    user_id: int,
    _: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_student_or_404(db, user_id)
    if user.account_status != AccountStatus.pending_verification:
        raise ValidationError("Only students with pending_verification status can be approved")
    user.account_status = AccountStatus.verified
    user.rejection_remarks = None
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}/reject", response_model=UserResponse)
async def reject_student(
    user_id: int,
    data: RejectStudentRequest,
    _: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_student_or_404(db, user_id)
    if user.account_status != AccountStatus.pending_verification:
        raise ValidationError("Only students with pending_verification status can be rejected")
    user.account_status = AccountStatus.rejected
    user.rejection_remarks = data.remarks
    await db.commit()
    await db.refresh(user)
    return user
