from pydantic import BaseModel, model_validator
from datetime import datetime
from typing import Any


def _derive_type(title: str) -> str:
    t = title.lower()
    if 'approved' in t:    return 'approved'
    if 'rejected' in t:    return 'rejected'
    if 'incomplete' in t:  return 'incomplete'
    if 'resubmit' in t:    return 'resubmit'
    if 'deadline' in t:    return 'deadline'
    if 'submitted' in t:   return 'status'
    return 'info'


def _derive_route(title: str, application_id: int | None) -> str | None:
    """
    Returns a role-agnostic route. Frontend prepends its base path:
      student → /student + route
      osfa    → /osfa + route
    """
    if application_id:
        return f"/applications/{application_id}"

    t = title.lower()
    if 'deadline' in t or 'scholarship' in t:
        return "/scholarships"
    if 'registration' in t:
        return "/registrations"

    return "/notifications"


class NotificationResponse(BaseModel):
    id: int
    title: str
    body: str
    is_read: bool
    application_id: int | None
    created_at: datetime

    # Fields expected by the frontend
    message: str = ''
    read: bool = False
    type: str = 'info'
    route: str | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode='after')
    def populate_frontend_fields(self) -> 'NotificationResponse':
        self.message = self.body
        self.read    = self.is_read
        self.type    = _derive_type(self.title)
        self.route   = _derive_route(self.title, self.application_id)
        return self
