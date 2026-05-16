from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_super_admin, require_osfa_or_admin
from app.models.user import User
from app.schemas.notification import NotificationResponse


class BroadcastRequest(BaseModel):
    title: str = Field(..., max_length=200)
    body: str = Field(..., max_length=2000)
from app.schemas.common import PaginatedResponse
from app.utils.pagination import paginate
from app.services import notification_service

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=PaginatedResponse[NotificationResponse])
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    items, total = await notification_service.list_notifications(db, current_user.id, page, page_size)
    return paginate(items, total, page, page_size)


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await notification_service.mark_read(db, current_user.id, notification_id)


@router.patch("/read-all")
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await notification_service.mark_all_read(db, current_user.id)
    return {"message": "All notifications marked as read"}


@router.post("/broadcast", status_code=200)
async def broadcast(
    data: BroadcastRequest,
    _: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    count = await notification_service.broadcast_announcement(db, data.title, data.body)
    return {"message": f"Announcement sent to {count} students."}


class AnnounceRequest(BaseModel):
    title: str = Field(..., max_length=200)
    body: str = Field(..., max_length=2000)
    target: str = "all"  # all | by_scholarship | by_status | selected
    scholarship_id: int | None = None
    status_filter: str | None = None
    student_ids: list[int] | None = None
    link: str | None = Field(None, max_length=500)


@router.post("/announce", status_code=200)
async def announce(
    data: AnnounceRequest,
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    count = await notification_service.send_announcement(
        db, data.title, data.body, data.target,
        scholarship_id=data.scholarship_id,
        status_filter=data.status_filter,
        student_ids=data.student_ids,
        link=data.link,
    )
    return {"message": f"Announcement sent to {count} students."}


@router.delete("/{notification_id}", status_code=204)
async def dismiss(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await notification_service.dismiss(db, current_user.id, notification_id)
