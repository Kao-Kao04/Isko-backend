import asyncio
from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_student
from app.models.user import User
from app.utils.storage import upload_file, get_signed_url
from app.services import registration_service
from app.exceptions import ForbiddenError

router = APIRouter(prefix="/api/registration", tags=["registration"])

ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB


def _validate_file(file: UploadFile) -> None:
    if file.content_type not in ALLOWED_TYPES:
        raise ForbiddenError("Only PDF, JPEG, or PNG files are accepted")


@router.post("/submit", status_code=200)
async def submit_registration(
    student_number: str = Form(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    middle_name: str | None = Form(default=None),
    college: str = Form(...),
    program: str = Form(...),
    year_level: int = Form(...),
    school_id: UploadFile = File(...),
    cor: UploadFile = File(...),
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    _validate_file(school_id)
    _validate_file(cor)

    school_id_bytes = await school_id.read()
    cor_bytes = await cor.read()

    if len(school_id_bytes) > MAX_FILE_SIZE or len(cor_bytes) > MAX_FILE_SIZE:
        raise ForbiddenError("File size must not exceed 5 MB")

    school_id_path = await upload_file(school_id_bytes, school_id.filename, school_id.content_type)
    cor_path = await upload_file(cor_bytes, cor.filename, cor.content_type)

    await registration_service.submit_registration(
        db=db,
        user=current_user,
        student_number=student_number,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        college=college,
        program=program,
        year_level=year_level,
        school_id_path=school_id_path,
        school_id_filename=school_id.filename,
        school_id_content_type=school_id.content_type,
        cor_path=cor_path,
        cor_filename=cor.filename,
        cor_content_type=cor.content_type,
    )

    return {"message": "Registration submitted. Awaiting OSFA review."}


@router.get("/my-documents")
async def my_registration_documents(
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    docs = await registration_service.get_registration_documents(db, current_user.id)
    urls = await asyncio.gather(*[get_signed_url(d.storage_path) for d in docs])
    return [
        {
            "id": d.id,
            "doc_type": d.doc_type,
            "filename": d.filename,
            "url": url,
            "uploaded_at": d.uploaded_at,
        }
        for d, url in zip(docs, urls)
    ]
