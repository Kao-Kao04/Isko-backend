from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user, require_osfa_or_admin, require_verified_student
from app.models.user import User, UserRole
from app.exceptions import NotFoundError, ForbiddenError
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
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(None),
    search: str | None = Query(None),
    scholarship_id: int | None = Query(None),
    sub_status: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await application_service.list_applications(db, current_user, page, page_size, status, search, scholarship_id, sub_status)
    return paginate(items, total, page, page_size)


@router.get("/count")
async def count_applications(
    status: str | None = Query(None),
    sub_status: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    total = await application_service.count_applications(db, current_user, status, sub_status)
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
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.update_application_status(db, application_id, data, current_user)


@router.patch("/{application_id}/eval-status", response_model=ApplicationResponse)
async def update_eval_status(
    application_id: int,
    data: EvalStatusUpdate,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.update_eval_status(db, application_id, data, current_user)


@router.patch("/{application_id}/eval-score", response_model=ApplicationResponse)
async def update_eval_score(
    application_id: int,
    data: EvalScoreUpdate,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.update_eval_score(db, application_id, data, current_user)


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
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.review_appeal(db, application_id, data, current_user)


class InternalNotesRequest(BaseModel):
    notes: str = Field(..., max_length=10000)

@router.patch("/{application_id}/notes", status_code=200)
async def update_internal_notes(
    application_id: int,
    data: InternalNotesRequest,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.models.application import Application as _App
    result = await db.execute(
        select(_App).options(selectinload(_App.scholarship))
        .where(_App.id == application_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise NotFoundError("Application", application_id)
    # OSFA staff are scoped to their own department's scholarships
    if current_user.role == UserRole.osfa_staff and current_user.department:
        if not app.scholarship or app.scholarship.category != current_user.department.value:
            raise ForbiddenError("You do not have access to this application")
    app.interview_notes = data.notes
    await db.commit()
    return {"message": "Notes saved.", "notes": data.notes}


@router.get("/{application_id}/audit", response_model=list[AuditEntryResponse])
async def get_audit(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await application_service.get_audit_trail(db, application_id, current_user)


@router.get("/{application_id}/completion-requirements")
async def get_completion_requirements(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select as _sel
    from app.models.application import Application, CompletionRequirement
    from app.models.user import UserRole
    # Students can only view their own; OSFA/admin can view any
    if current_user.role == UserRole.student:
        app_check = (await db.execute(_sel(Application).where(Application.id == application_id))).scalar_one_or_none()
        if not app_check or app_check.student_id != current_user.id:
            from app.exceptions import ForbiddenError
            raise ForbiddenError("Not your application")
    reqs = (await db.execute(
        _sel(CompletionRequirement)
        .where(CompletionRequirement.application_id == application_id)
        .order_by(CompletionRequirement.submitted_at)
    )).scalars().all()
    return [
        {
            "id": r.id,
            "requirement_type": r.requirement_type,
            "file_url": r.file_url,
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
        }
        for r in reqs
    ]
