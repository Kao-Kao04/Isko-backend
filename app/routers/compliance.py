from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.dependencies import get_current_user, require_osfa_or_admin
from app.models.user import User
from app.services import compliance_service
from app.exceptions import NotFoundError

router = APIRouter(prefix="/api", tags=["compliance"])


# ── Compliance document type schemas ─────────────────────────────────────────

class ComplianceDocTypeCreate(BaseModel):
    name: str
    description: str | None = None
    is_required: bool = True
    order: int = 0


class ComplianceDocTypeResponse(BaseModel):
    id: int
    scholarship_id: int
    name: str
    description: str | None
    is_required: bool
    order: int

    model_config = {"from_attributes": True}


class ComplianceDocSubmit(BaseModel):
    requirement_type: str   # must match a ComplianceDocumentType.name
    file_url: str | None = None
    notes: str | None = None


class ComplianceDocResponse(BaseModel):
    id: int
    application_id: int
    requirement_type: str
    file_url: str | None
    notes: str | None
    submitted_at: str | None
    is_verified: bool
    verified_by: int | None
    verified_at: str | None

    model_config = {"from_attributes": True}


# ── Scholarship compliance doc type config (OSFA) ────────────────────────────

@router.get("/scholarships/{scholarship_id}/compliance-docs", response_model=list[ComplianceDocTypeResponse])
async def list_compliance_doc_types(
    scholarship_id: int,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await compliance_service.get_compliance_doc_types(db, scholarship_id)


@router.post("/scholarships/{scholarship_id}/compliance-docs", response_model=ComplianceDocTypeResponse, status_code=201)
async def create_compliance_doc_type(
    scholarship_id: int,
    data: ComplianceDocTypeCreate,
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await compliance_service.create_compliance_doc_type(
        db, scholarship_id, data.name, data.description, data.is_required, data.order
    )


@router.delete("/scholarships/compliance-docs/{doc_type_id}", status_code=204)
async def delete_compliance_doc_type(
    doc_type_id: int,
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    await compliance_service.delete_compliance_doc_type(db, doc_type_id)


# ── Application compliance submissions (student + OSFA) ──────────────────────

@router.get("/applications/{application_id}/compliance", response_model=list[ComplianceDocResponse])
async def list_compliance_docs(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await compliance_service.list_compliance_docs(db, application_id)


@router.post("/applications/{application_id}/compliance", response_model=ComplianceDocResponse, status_code=201)
async def submit_compliance_doc(
    application_id: int,
    data: ComplianceDocSubmit,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await compliance_service.submit_compliance_doc(
        db, application_id, data.requirement_type, data.file_url, data.notes, current_user
    )


@router.patch("/applications/{application_id}/compliance/{requirement_id}/verify", response_model=ComplianceDocResponse)
async def verify_compliance_doc(
    application_id: int,
    requirement_id: int,
    actor: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await compliance_service.verify_compliance_doc(db, application_id, requirement_id, actor)


# ── Scholar benefit release + thank you letter ────────────────────────────────

@router.patch("/scholars/{scholar_id}/semester-records/{record_id}/release-benefit", status_code=200)
async def release_benefit(
    scholar_id: int,
    record_id: int,
    actor: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.services.scholar_service import release_benefit as _release
    record = await _release(db, scholar_id, record_id, actor)
    return {"message": "Benefit released successfully.", "benefit_released_at": record.benefit_released_at}


@router.patch("/scholars/{scholar_id}/semester-records/{record_id}/thank-you", status_code=200)
async def submit_thank_you(
    scholar_id: int,
    record_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.scholar_service import submit_thank_you as _submit
    record = await _submit(db, scholar_id, record_id, current_user)
    return {"message": "Thank you letter recorded.", "thank_you_submitted_at": record.thank_you_submitted_at}


# ── Document generation ───────────────────────────────────────────────────────

@router.get("/applications/{application_id}/documents/confirmation-letter", response_class=HTMLResponse)
async def get_confirmation_letter(
    application_id: int,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.application import Application
    from app.models.user import StudentProfile
    from app.utils.document_generator import generate_confirmation_letter
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Application)
        .options(
            selectinload(Application.scholarship),
            selectinload(Application.student).selectinload(StudentProfile.user if hasattr(StudentProfile, 'user') else StudentProfile),
        )
        .where(Application.id == application_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise NotFoundError("Application", application_id)

    profile = app.student.student_profile if app.student else None
    scholar_name = f"{profile.first_name} {profile.last_name}" if profile else "Scholar"
    student_number = profile.student_number if profile else "N/A"
    sch = app.scholarship

    html = generate_confirmation_letter(
        scholar_name=scholar_name,
        student_number=student_number,
        scholarship_name=sch.name if sch else "Scholarship",
        scholarship_type=sch.scholarship_type if sch else None,
        amount_raw=sch.amount_raw if sch else None,
        period=sch.period if sch else None,
        min_gwa=sch.min_gwa if sch else None,
    )
    return HTMLResponse(content=html)


@router.get("/applications/{application_id}/documents/terms", response_class=HTMLResponse)
async def get_scholar_terms(
    application_id: int,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.application import Application
    from app.models.user import StudentProfile
    from app.utils.document_generator import generate_scholar_terms
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Application)
        .options(selectinload(Application.scholarship), selectinload(Application.student))
        .where(Application.id == application_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise NotFoundError("Application", application_id)

    profile = app.student.student_profile if app.student else None
    scholar_name = f"{profile.first_name} {profile.last_name}" if profile else "Scholar"
    sch = app.scholarship

    html = generate_scholar_terms(
        scholar_name=scholar_name,
        scholarship_name=sch.name if sch else "Scholarship",
        min_gwa=sch.min_gwa if sch else None,
        max_semesters=sch.max_semesters if sch else None,
        requires_thank_you_letter=sch.requires_thank_you_letter if sch else False,
    )
    return HTMLResponse(content=html)
