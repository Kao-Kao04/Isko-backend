from pydantic import BaseModel, model_validator
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
    # Frontend-expected aliases
    file_name: str = ""
    file_url: str | None = None
    flagged: bool = False
    flag_reason: str | None = None
    requirement_name: str = ""

    model_config = {"from_attributes": True}

    @model_validator(mode='after')
    def populate_aliases(self):
        self.file_name = self.filename
        self.file_url = self.url
        self.flagged = self.status == DocumentStatus.flagged
        if not self.requirement_name:
            self.requirement_name = self.filename
        return self


class FlagDocsRequest(BaseModel):
    rejected_doc_ids: List[int]
