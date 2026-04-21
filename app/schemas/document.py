from pydantic import BaseModel
from datetime import datetime
from typing import List
from app.models.document import DocumentStatus


class DocumentResponse(BaseModel):
    id: int
    application_id: int
    requirement_id: int | None
    filename: str
    content_type: str
    file_size: int
    status: DocumentStatus
    uploaded_at: datetime
    url: str | None = None

    model_config = {"from_attributes": True}


class FlagDocsRequest(BaseModel):
    rejected_doc_ids: List[int]
