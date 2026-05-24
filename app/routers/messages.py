from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
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
    body: str = Field(..., max_length=5000)


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
    from app.models.scholarship import Scholarship
    app = (await db.execute(
        select(Application)
        .options(
            selectinload(Application.student).selectinload(User.student_profile),
            selectinload(Application.messages).selectinload(ApplicationMessage.sender),
            selectinload(Application.scholarship),
        )
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
    if current_user.role == UserRole.osfa_staff and current_user.department and app.scholarship:
        if app.scholarship.category != current_user.department:
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Not your department's application"})

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

    if current_user.role == UserRole.super_admin:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Super admin cannot send messages"})
    if current_user.role == UserRole.student and app.student_id != current_user.id:
        raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Not your application"})
    if current_user.role == UserRole.osfa_staff and current_user.department and app.scholarship:
        if app.scholarship.category != current_user.department:
            raise HTTPException(status_code=403, detail={"code": "FORBIDDEN", "message": "Not your department's application"})

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
        student_name = ""
        if app.student and app.student.student_profile:
            p = app.student.student_profile
            student_name = f"{p.first_name} {p.last_name}".strip()
        else:
            student_name = app.student.email if app.student else "A student"

        # Only notify OSFA staff in the matching department (public/private)
        dept_filter = app.scholarship.category if app.scholarship and app.scholarship.category else None
        staff_query = select(User).where(User.role == UserRole.osfa_staff, User.is_active == True)
        if dept_filter:
            staff_query = staff_query.where(User.department == dept_filter)
        osfa_staff = (await db.execute(staff_query)).scalars().all()

        for staff in osfa_staff:
            try:
                await create_notification(
                    db=db,
                    user_id=staff.id,  # type: ignore[arg-type]
                    title=f"New message from {student_name}",
                    body=f"Application #{application_id}: {data.body.strip()[:80]}{'…' if len(data.body.strip()) > 80 else ''}",
                    application_id=application_id,
                    link=f"/osfa/applicants/{application_id}",
                )
            except Exception:
                pass  # Never block message delivery due to notification failure
    else:
        # OSFA replied — notify the student
        try:
            await create_notification(
                db=db,
                user_id=app.student_id,  # type: ignore[arg-type]
                title="New reply from OSFA",
                body=f"OSFA replied to your message on application #{application_id}.",
                application_id=application_id,
                link=f"/student/applications/{application_id}",
            )
        except Exception:
            pass

    await db.commit()
    return _fmt(msg)


# ── Inbox ─────────────────────────────────────────────────────────────────────

@router.get("/inbox")
async def get_inbox(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all conversations (applications with ≥1 message) for the current user."""
    from sqlalchemy import func as _func, desc, case
    from app.models.scholarship import Scholarship

    # Aggregate per application: latest message time, total count, unread count
    unread_expr = _func.sum(
        case((
            (ApplicationMessage.is_read == False) & (ApplicationMessage.sender_id != current_user.id),
            1,
        ), else_=0)
    )

    subq = (
        select(
            ApplicationMessage.application_id,
            _func.max(ApplicationMessage.created_at).label("last_at"),
            _func.count(ApplicationMessage.id).label("msg_count"),
            unread_expr.label("unread"),
        )
        .group_by(ApplicationMessage.application_id)
        .subquery()
    )

    q = (
        select(Application, subq.c.last_at, subq.c.msg_count, subq.c.unread)
        .join(subq, Application.id == subq.c.application_id)
        .options(
            selectinload(Application.scholarship),
            selectinload(Application.student).selectinload(User.student_profile),
        )
        .order_by(desc(subq.c.last_at))
    )

    if current_user.role == UserRole.student:
        q = q.where(Application.student_id == current_user.id)
    elif current_user.role == UserRole.osfa_staff and current_user.department:
        q = (q
             .join(Scholarship, Application.scholarship_id == Scholarship.id)
             .where(Scholarship.category == current_user.department.value))

    try:
        rows = (await db.execute(q)).all()
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("inbox query failed: %s", exc, exc_info=True)
        return {"items": [], "total": 0, "error": str(exc)}

    result = []
    for app, last_at, msg_count, unread in rows:
        p = app.student.student_profile if app.student else None
        student_name = (
            f"{p.first_name} {p.last_name}".strip() if p
            else (app.student.email if app.student else f"Student #{app.student_id}")
        )
        result.append({
            "application_id":   app.id,
            "student_name":     student_name,
            "student_email":    app.student.email if app.student else "",
            "scholarship_name": app.scholarship.name if app.scholarship else f"Scholarship #{app.scholarship_id}",
            "last_message_at":  last_at.isoformat() if last_at else None,
            "message_count":    int(msg_count or 0),
            "unread_count":     int(unread or 0),
        })
    return {"items": result, "total": len(result)}
