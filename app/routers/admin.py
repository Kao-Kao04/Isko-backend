from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr
from typing import Optional

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole, DepartmentEnum, AccountStatus
from app.utils.security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


def require_super_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.super_admin:
        raise HTTPException(status_code=403, detail="Super admin access required")
    return current_user


class StaffCreate(BaseModel):
    email: EmailStr
    password: str
    department: str


class StaffUpdate(BaseModel):
    department: Optional[str] = None
    is_active: Optional[bool] = None


class StaffResponse(BaseModel):
    id: int
    email: str
    department: Optional[str]
    is_active: bool
    created_at: str

    model_config = {"from_attributes": True}


@router.get("/staff", response_model=list[StaffResponse])
async def list_staff(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    result = await db.execute(
        select(User).where(User.role == UserRole.osfa_staff).order_by(User.created_at.desc())
    )
    staff = result.scalars().all()
    return [StaffResponse(
        id=s.id,
        email=s.email,
        department=s.department.value if s.department else None,
        is_active=s.is_active,
        created_at=s.created_at.isoformat(),
    ) for s in staff]


@router.post("/staff", response_model=StaffResponse, status_code=201)
async def create_staff(
    data: StaffCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        role=UserRole.osfa_staff,
        department=DepartmentEnum(data.department),
        is_verified=True,
        account_status=AccountStatus.approved,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return StaffResponse(
        id=user.id,
        email=user.email,
        department=user.department.value if user.department else None,
        is_active=user.is_active,
        created_at=user.created_at.isoformat(),
    )


@router.patch("/staff/{staff_id}", response_model=StaffResponse)
async def update_staff(
    staff_id: int,
    data: StaffUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    result = await db.execute(
        select(User).where(User.id == staff_id, User.role == UserRole.osfa_staff)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Staff not found")
    if data.department is not None:
        user.department = DepartmentEnum(data.department)
    if data.is_active is not None:
        user.is_active = data.is_active
    await db.commit()
    await db.refresh(user)
    return StaffResponse(
        id=user.id,
        email=user.email,
        department=user.department.value if user.department else None,
        is_active=user.is_active,
        created_at=user.created_at.isoformat(),
    )
