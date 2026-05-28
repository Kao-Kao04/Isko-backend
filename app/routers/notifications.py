from fastapi import APIRouter, Depends, Query, UploadFile, File
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_super_admin, require_osfa_or_admin
from app.models.user import User, UserRole
from app.exceptions import ForbiddenError
from app.schemas.notification import NotificationResponse
from app.schemas.common import PaginatedResponse
from app.utils.pagination import paginate
from app.services import notification_service


class BroadcastRequest(BaseModel):
    title: str = Field(..., max_length=200)
    body: str = Field(..., max_length=2000)

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
    image_url: str | None = None

    @field_validator("image_url")
    @classmethod
    def must_be_https(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://"):
            raise ValueError("image_url must be a secure https:// URL")
        return v


@router.post("/announce", status_code=200)
async def announce(
    data: AnnounceRequest,
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    if (current_user.role == UserRole.osfa_staff and current_user.department
            and data.target == "by_scholarship" and data.scholarship_id):
        from sqlalchemy import select as _sel
        from app.models.scholarship import Scholarship
        sch_row = await db.execute(_sel(Scholarship).where(Scholarship.id == data.scholarship_id))
        sch = sch_row.scalar_one_or_none()
        if sch and sch.category != current_user.department:
            raise ForbiddenError("Cannot send announcements for scholarships outside your department")
    count = await notification_service.send_announcement(
        db, data.title, data.body, data.target,
        scholarship_id=data.scholarship_id,
        status_filter=data.status_filter,
        student_ids=data.student_ids,
        link=data.link,
        image_url=data.image_url,
    )
    return {"message": f"Announcement sent to {count} students."}


@router.post("/media/upload")
async def upload_announcement_image(
    file: UploadFile = File(...),
    _: User = Depends(require_osfa_or_admin),
):
    content_type = file.content_type or "application/octet-stream"
    if content_type not in ("image/jpeg", "image/png", "image/webp", "image/gif"):
        from app.exceptions import ValidationError
        raise ValidationError("Image must be JPEG, PNG, WEBP, or GIF")
    file_bytes = await file.read()
    if len(file_bytes) > 5 * 1024 * 1024:
        from app.exceptions import ValidationError
        raise ValidationError("Image must be under 5 MB")
    from app.utils.storage import upload_file, get_signed_url
    path = await upload_file(file_bytes, file.filename or "image.jpg", content_type)
    # 1-year signed URL — announcement images are not sensitive
    url = await get_signed_url(path, expires_in=31_536_000)
    return {"url": url}


@router.delete("/{notification_id}", status_code=204)
async def dismiss(
    notification_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await notification_service.dismiss(db, current_user.id, notification_id)
