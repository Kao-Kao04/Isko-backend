from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User, UserRole
from app.models.application import Application
from app.models.message import ApplicationMessage
from app.services.notification_service import create_notification

router = APIRouter(prefix="/api/applications", tags=["messages"])


class MessageRequest(BaseModel):
    body: str


def _fmt(m: ApplicationMessage) -> dict:
    return {
        "id":             m.id,
        "application_id": m.application_id,
        "sender_id":      m.sender_id,
        "sender_email":   m.sender.email if m.sender else "—",
        "sender_role":    m.sender.role.value if m.sender else "unknown",
        "body":           m.body,
        "is_read":        m.is_read,
        "created_at":     m.created_at.isoformat(),
    }


async def _get_application(application_id: int, db: AsyncSession) -> Application:
    app = (await db.execute(
        select(Application)
        .options(selectinload(Application.student), selectinload(Application.messages).selectinload(ApplicationMessage.sender))
        .where(Application.id == application_id)
    )).scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Application not found"})
    return app


@router.get("/{application_id}/messages")
async def list_messages(
    application_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    app = await _get_application(application_id, db)

    if current_user.role == UserRole.student and app.student_id != current_user.id:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Not your application"})

    # Mark messages from the other party as read
    for m in app.messages:
        if not m.is_read and m.sender_id != current_user.id:
            m.is_read = True
    await db.commit()

    return {"items": [_fmt(m) for m in app.messages]}


@router.post("/{application_id}/messages", status_code=201)
async def send_message(
    application_id: int,
    data: MessageRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not data.body.strip():
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "Message cannot be empty"})

    app = await _get_application(application_id, db)

    if current_user.role == UserRole.student and app.student_id != current_user.id:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Not your application"})

    msg = ApplicationMessage(
        application_id=application_id,
        sender_id=current_user.id,
        body=data.body.strip(),
    )
    db.add(msg)
    await db.flush()
    await db.refresh(msg, ["sender"])

    # Notify the other party
    if current_user.role == UserRole.student:
        # Notify all OSFA staff — get one staff to notify (or broadcast)
        # For simplicity, create a notification for the application owner side
        pass  # OSFA sees unread badge; no personal notification needed
    else:
        # OSFA replied — notify the student
        await create_notification(
            db=db,
            user_id=app.student_id,
            title="New reply from OSFA",
            body=f"OSFA replied to your message on application #{application_id}.",
            application_id=application_id,
            link=f"/student/applications/{application_id}",
        )

    await db.commit()
    return _fmt(msg)
