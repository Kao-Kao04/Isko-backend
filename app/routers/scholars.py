from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_osfa_or_admin, require_student
from app.models.user import User
from app.schemas.scholar import (
    ScholarResponse, ScholarStatusUpdate,
    SemesterRecordCreate, SemesterRecordUpdate, SemesterRecordResponse,
)
from app.schemas.common import PaginatedResponse
from app.utils.pagination import paginate
from app.services import scholar_service

router = APIRouter(prefix="/api/scholars", tags=["scholars"])


@router.get("/me", response_model=list[ScholarResponse])
async def my_scholars(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    return await scholar_service.get_scholars_by_student(db, current_user.id)


@router.get("", response_model=PaginatedResponse[ScholarResponse])
async def list_scholars(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    items, total = await scholar_service.list_scholars(db, page, page_size)
    return paginate(items, total, page, page_size)


@router.get("/{scholar_id}", response_model=ScholarResponse)
async def get_scholar(
    scholar_id: int,
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await scholar_service.get_scholar(db, scholar_id)


@router.patch("/{scholar_id}/status", response_model=ScholarResponse)
async def update_status(
    scholar_id: int,
    data: ScholarStatusUpdate,
    actor: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await scholar_service.update_scholar_status(db, scholar_id, data, actor)


@router.post("/{scholar_id}/semester-records", response_model=SemesterRecordResponse, status_code=201)
async def add_semester_record(
    scholar_id: int,
    data: SemesterRecordCreate,
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await scholar_service.add_semester_record(db, scholar_id, data)


@router.put("/{scholar_id}/semester-records/{record_id}", response_model=SemesterRecordResponse)
async def update_semester_record(
    scholar_id: int,
    record_id: int,
    data: SemesterRecordUpdate,
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await scholar_service.update_semester_record(db, scholar_id, record_id, data)
