from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_osfa
from app.models.user import User
from app.schemas.scholarship import ScholarshipCreate, ScholarshipUpdate, ScholarshipStatusUpdate, ScholarshipResponse
from app.schemas.common import PaginatedResponse
from app.utils.pagination import paginate
from app.services import scholarship_service

router = APIRouter(prefix="/api/scholarships", tags=["scholarships"])


@router.get("", response_model=PaginatedResponse[ScholarshipResponse])
async def list_scholarships(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await scholarship_service.list_scholarships(db, current_user, page, page_size)
    return paginate(items, total, page, page_size)


@router.get("/{scholarship_id}", response_model=ScholarshipResponse)
async def get_scholarship(
    scholarship_id: int,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await scholarship_service.get_scholarship(db, scholarship_id)


@router.post("", response_model=ScholarshipResponse, status_code=201)
async def create_scholarship(
    data: ScholarshipCreate,
    current_user: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    return await scholarship_service.create_scholarship(db, data, current_user)


@router.put("/{scholarship_id}", response_model=ScholarshipResponse)
async def update_scholarship(
    scholarship_id: int,
    data: ScholarshipUpdate,
    _: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    return await scholarship_service.update_scholarship(db, scholarship_id, data)


@router.delete("/{scholarship_id}", status_code=204)
async def delete_scholarship(
    scholarship_id: int,
    _: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    await scholarship_service.delete_scholarship(db, scholarship_id)


@router.patch("/{scholarship_id}/status", response_model=ScholarshipResponse)
async def update_status(
    scholarship_id: int,
    data: ScholarshipStatusUpdate,
    _: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    return await scholarship_service.update_status(db, scholarship_id, data)


@router.post("/{scholarship_id}/duplicate", response_model=ScholarshipResponse, status_code=201)
async def duplicate_scholarship(
    scholarship_id: int,
    current_user: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    return await scholarship_service.duplicate_scholarship(db, scholarship_id, current_user.id)
