from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database import get_db
from app.dependencies import require_super_admin, require_osfa_or_admin, require_student, get_current_user
from app.models.user import User
from app.schemas.academic_period import (
    AcademicPeriodCreate, AcademicPeriodResponse,
    GwaSubmissionResponse, GwaSubmissionReview, GwaSubmissionReject,
)
from app.services import academic_period_service
from app.utils.storage import get_signed_url, upload_file
from app.utils.file_validation import validate_file_bytes
from app.exceptions import ValidationError

router = APIRouter(prefix="/api/academic-periods", tags=["academic-periods"])


def _with_url(sub, url: str) -> GwaSubmissionResponse:
    out = GwaSubmissionResponse.model_validate(sub)
    out.proof_url = url
    return out


@router.get("/current", response_model=Optional[AcademicPeriodResponse])
async def get_current_period(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await academic_period_service.get_current_period(db)


@router.get("", response_model=list[AcademicPeriodResponse])
async def list_periods(
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await academic_period_service.list_periods(db)


@router.post("", response_model=AcademicPeriodResponse, status_code=201)
async def create_period(
    data: AcademicPeriodCreate,
    actor: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await academic_period_service.create_period(db, data, actor)


@router.delete("/{period_id}", status_code=204)
async def delete_period(
    period_id: int,
    actor: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    await academic_period_service.delete_period(db, period_id, actor)


# ── Pending GWA submissions (OSFA review queue) ───────────────────────────────

@router.get("/gwa-submissions/pending", response_model=list[GwaSubmissionResponse])
async def list_pending_submissions(
    actor: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    subs = await academic_period_service.list_pending_gwa_submissions(db, actor)
    results = []
    for sub in subs:
        url = await get_signed_url(sub.proof_path)
        results.append(_with_url(sub, url))
    return results
