from pydantic import BaseModel
from datetime import datetime


class NotificationResponse(BaseModel):
    id: int
    title: str
    body: str
    is_read: bool
    application_id: int | None
    created_at: datetime

    model_config = {"from_attributes": True}
