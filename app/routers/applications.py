from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_osfa, require_verified_student
from app.models.user import User
from app.schemas.application import (
    ApplicationCreate, ApplicationStatusUpdate, EvalStatusUpdate, EvalScoreUpdate,
    AppealCreate, AppealReview, ApplicationResponse, AuditEntryResponse, AppealResponse,
)
from app.schemas.common import PaginatedResponse
from app.utils.pagination import paginate
from app.services import application_service

router = APIRouter(prefix="/api/applications", tags=["applications"])


@router.get("", response_model=PaginatedResponse[ApplicationResponse])
async def list_applications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=500),
    status: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await application_service.list_applications(db, current_user, page, page_size, status)
    return paginate(items, total, page, page_size)


@router.get("/count")
async def count_applications(
    status: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _, total = await application_service.list_applications(db, current_user, 1, 1, status)
    return {"count": total}


@router.get("/{application_id}", response_model=ApplicationResponse)
async def get_application(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.get_application(db, application_id, current_user)


@router.post("", response_model=ApplicationResponse, status_code=201)
async def submit_application(
    data: ApplicationCreate,
    current_user: User = Depends(require_verified_student),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.submit_application(db, data, current_user)


@router.patch("/{application_id}/resubmit", response_model=ApplicationResponse)
async def resubmit_application(
    application_id: int,
    current_user: User = Depends(require_verified_student),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.resubmit_application(db, application_id, current_user)


@router.patch("/{application_id}/withdraw", status_code=204)
async def withdraw_application(
    application_id: int,
    current_user: User = Depends(require_verified_student),
    db: AsyncSession = Depends(get_db),
):
    await application_service.withdraw_application(db, application_id, current_user)


@router.patch("/{application_id}/status", response_model=ApplicationResponse)
async def update_status(
    application_id: int,
    data: ApplicationStatusUpdate,
    current_user: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.update_application_status(db, application_id, data, current_user)


@router.patch("/{application_id}/eval-status", response_model=ApplicationResponse)
async def update_eval_status(
    application_id: int,
    data: EvalStatusUpdate,
    current_user: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.update_eval_status(db, application_id, data, current_user)


@router.patch("/{application_id}/eval-score", response_model=ApplicationResponse)
async def update_eval_score(
    application_id: int,
    data: EvalScoreUpdate,
    _: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.update_eval_score(db, application_id, data)


@router.post("/{application_id}/appeal", response_model=AppealResponse, status_code=201)
async def file_appeal(
    application_id: int,
    data: AppealCreate,
    current_user: User = Depends(require_verified_student),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.file_appeal(db, application_id, data, current_user)


@router.patch("/{application_id}/appeal", response_model=AppealResponse)
async def review_appeal(
    application_id: int,
    data: AppealReview,
    current_user: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.review_appeal(db, application_id, data, current_user)


@router.get("/{application_id}/audit", response_model=list[AuditEntryResponse])
async def get_audit(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.get_audit_trail(db, application_id, current_user)
