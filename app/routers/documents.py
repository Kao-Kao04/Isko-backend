from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_osfa
from app.models.user import User
from app.schemas.document import DocumentResponse, FlagDocsRequest
from app.services import document_service
from app.utils.storage import get_public_url

router = APIRouter(prefix="/api/applications/{application_id}/documents", tags=["documents"])


def _enrich(doc) -> DocumentResponse:
    resp = DocumentResponse.model_validate(doc)
    resp.url = get_public_url(doc.storage_path)
    return resp


@router.post("", response_model=DocumentResponse, status_code=201)
async def upload_document(
    application_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    doc = await document_service.upload_document(db, application_id, file, current_user)
    return _enrich(doc)


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    application_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    docs = await document_service.list_documents(db, application_id, current_user)
    return [_enrich(d) for d in docs]


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
    _: User = Depends(require_osfa),
    db: AsyncSession = Depends(get_db),
):
    await document_service.flag_documents(db, application_id, data, _)
    return {"message": "Documents flagged"}
