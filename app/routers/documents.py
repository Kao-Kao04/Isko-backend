import asyncio
from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_osfa_or_admin
from app.models.user import User
from app.schemas.document import DocumentResponse, FlagDocsRequest
from app.services import document_service
from app.utils.storage import get_signed_url

router = APIRouter(prefix="/api/applications/{application_id}/documents", tags=["documents"])


async def _enrich(doc) -> DocumentResponse:
    resp = DocumentResponse.model_validate(doc)
    url = await get_signed_url(doc.storage_path)
    resp.url = url
    resp.file_url = url
    resp.requirement_name = (doc.requirement.name if doc.requirement and doc.requirement.name else doc.filename)
    resp.file_name = doc.filename
    resp.flagged = doc.status == "flagged"
    return resp


@router.post("", response_model=DocumentResponse, status_code=201)
async def upload_document(
    application_id: int,
    file: UploadFile = File(...),
    requirement_name: str | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_service.upload_document(db, application_id, file, current_user, requirement_name)
    return await _enrich(doc)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    docs = await document_service.list_documents(db, application_id, current_user)
    return await asyncio.gather(*[_enrich(d) for d in docs])


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    application_id: int,
    doc_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await document_service.delete_document(db, application_id, doc_id, current_user)


@router.patch("/flag")
async def flag_documents(
    application_id: int,
    data: FlagDocsRequest,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    await document_service.flag_documents(db, application_id, data, current_user)
    return {"message": "Documents flagged"}
