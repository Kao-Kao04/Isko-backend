from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.models.document import ApplicationDocument, DocumentStatus
from app.models.application import Application
from app.models.scholarship import ScholarshipRequirement
from app.models.user import UserRole
from app.schemas.document import FlagDocsRequest
from app.utils.storage import upload_file, get_public_url, delete_file
from app.exceptions import NotFoundError, ForbiddenError, ValidationError

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_TYPES = {"application/pdf", "image/jpeg", "image/png"}


async def upload_document(
    db: AsyncSession, application_id: int, file: UploadFile, user,
    requirement_name: str | None = None,
) -> ApplicationDocument:
    result = await db.execute(select(Application).where(Application.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise NotFoundError("Application", application_id)
    if user.role == UserRole.student and app.student_id != user.id:
        raise ForbiddenError()

    if file.content_type not in ALLOWED_TYPES:
        raise ValidationError("Only PDF, JPG, and PNG files are allowed")

    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise ValidationError("File exceeds 5 MB limit")

    storage_path = await upload_file(contents, file.filename, file.content_type)

    requirement_id = None
    if requirement_name:
        req_result = await db.execute(
            select(ScholarshipRequirement).where(
                ScholarshipRequirement.scholarship_id == app.scholarship_id,
                ScholarshipRequirement.name == requirement_name,
            )
        )
        req = req_result.scalar_one_or_none()
        if req:
            requirement_id = req.id

    doc = ApplicationDocument(
        application_id=application_id,
        requirement_id=requirement_id,
        filename=requirement_name or file.filename,
        storage_path=storage_path,
        content_type=file.content_type,
        file_size=len(contents),
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)
    return doc


async def list_documents(db: AsyncSession, application_id: int, user) -> list[ApplicationDocument]:
    result = await db.execute(select(Application).where(Application.id == application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise NotFoundError("Application", application_id)
    if user.role == UserRole.student and app.student_id != user.id:
        raise ForbiddenError()

    docs_result = await db.execute(
        select(ApplicationDocument).where(ApplicationDocument.application_id == application_id)
    )
    return docs_result.scalars().all()


async def delete_document(db: AsyncSession, application_id: int, doc_id: int, user) -> None:
    result = await db.execute(
        select(ApplicationDocument).where(
            ApplicationDocument.id == doc_id,
            ApplicationDocument.application_id == application_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise NotFoundError("Document", doc_id)

    app_result = await db.execute(select(Application).where(Application.id == application_id))
    app = app_result.scalar_one_or_none()
    if user.role == UserRole.student and app.student_id != user.id:
        raise ForbiddenError()

    await delete_file(doc.storage_path)
    await db.delete(doc)
    await db.commit()


async def flag_documents(db: AsyncSession, application_id: int, data: FlagDocsRequest, staff) -> None:
    await db.execute(
        update(ApplicationDocument)
        .where(
            ApplicationDocument.application_id == application_id,
            ApplicationDocument.id.in_(data.rejected_doc_ids),
        )
        .values(status=DocumentStatus.flagged)
    )
    await db.execute(
        update(ApplicationDocument)
        .where(
            ApplicationDocument.application_id == application_id,
            ApplicationDocument.id.notin_(data.rejected_doc_ids),
        )
        .values(status=DocumentStatus.submitted)
    )
    await db.commit()
