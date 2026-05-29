from fastapi import APIRouter, Depends, Query, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional

from app.database import get_db
from app.dependencies import require_osfa_or_admin, require_student, get_current_user
from app.models.user import User
from app.schemas.scholar import (
    ScholarResponse, ScholarStatusUpdate, AllowanceUpdate,
    SemesterRecordCreate, SemesterRecordUpdate, SemesterRecordResponse,
)
from app.schemas.academic_period import GwaSubmissionResponse, GwaSubmissionReview, GwaSubmissionReject
from app.schemas.common import PaginatedResponse
from app.utils.pagination import paginate
from app.services import scholar_service
from app.services import academic_period_service
from app.utils.storage import get_signed_url, upload_file
from app.utils.file_validation import validate_file_bytes

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
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    items, total = await scholar_service.list_scholars(db, current_user, page, page_size)
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
    actor: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await scholar_service.add_semester_record(db, scholar_id, data, actor)


@router.patch("/{scholar_id}/allowance", response_model=ScholarResponse)
async def update_allowance(
    scholar_id: int,
    data: AllowanceUpdate,
    actor: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    scholar = await scholar_service.get_scholar(db, scholar_id)
    scholar_service._check_dept_scholar(scholar, actor)
    update = data.model_dump(exclude_unset=True)
    for field, value in update.items():
        setattr(scholar, field, value)
    await db.commit()
    return await scholar_service.get_scholar(db, scholar_id)


@router.put("/{scholar_id}/semester-records/{record_id}", response_model=SemesterRecordResponse)
async def update_semester_record(
    scholar_id: int,
    record_id: int,
    data: SemesterRecordUpdate,
    actor: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await scholar_service.update_semester_record(db, scholar_id, record_id, data, actor)


# ── GWA Submission endpoints ──────────────────────────────────────────────────

def _sub_with_url(sub, url: str) -> GwaSubmissionResponse:
    out = GwaSubmissionResponse.model_validate(sub)
    out.proof_url = url
    return out


@router.post("/{scholar_id}/gwa-submissions", response_model=GwaSubmissionResponse, status_code=201)
async def submit_gwa(
    scholar_id: int,
    period_id: int = Form(...),
    declared_gwa: Optional[str] = Form(None),
    has_grade_below_2_5: bool = Form(False),
    proof: UploadFile = File(...),
    student: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    contents = await proof.read()
    validate_file_bytes(contents, proof.filename or "")
    proof_path = await upload_file(contents, proof.filename or "proof", proof.content_type or "application/octet-stream")
    sub = await academic_period_service.submit_gwa(
        db, scholar_id, period_id, declared_gwa, has_grade_below_2_5, proof_path, student
    )
    url = await get_signed_url(str(sub.proof_path))
    return _sub_with_url(sub, url)


@router.get("/{scholar_id}/gwa-submissions", response_model=list[GwaSubmissionResponse])
async def list_gwa_submissions(
    scholar_id: int,
    actor: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    subs = await academic_period_service.list_gwa_submissions(db, scholar_id, actor)
    results = []
    for sub in subs:
        url = await get_signed_url(str(sub.proof_path))
        results.append(_sub_with_url(sub, url))
    return results


@router.patch("/{scholar_id}/gwa-submissions/{sub_id}/approve", response_model=GwaSubmissionResponse)
async def approve_gwa_submission(
    scholar_id: int,
    sub_id: int,
    data: GwaSubmissionReview,
    actor: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    sub = await academic_period_service.approve_gwa_submission(db, scholar_id, sub_id, data, actor)
    url = await get_signed_url(str(sub.proof_path))
    return _sub_with_url(sub, url)


@router.patch("/{scholar_id}/gwa-submissions/{sub_id}/reject", response_model=GwaSubmissionResponse)
async def reject_gwa_submission(
    scholar_id: int,
    sub_id: int,
    data: GwaSubmissionReject,
    actor: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    sub = await academic_period_service.reject_gwa_submission(db, scholar_id, sub_id, data, actor)
    url = await get_signed_url(str(sub.proof_path))
    return _sub_with_url(sub, url)
