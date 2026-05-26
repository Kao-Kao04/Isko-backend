import asyncio
import html as _html
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.config import settings
from app.database import get_db
from app.dependencies import require_super_admin, require_osfa_or_admin, get_current_user, get_optional_user
# get_current_user is used by /api/student/contacts endpoint
from app.limiter import limiter
from app.models.message import ContactInquiry
from app.models.user import User

router = APIRouter(tags=["contact"])


class ContactRequest(BaseModel):
    name: str = Field(..., max_length=200)
    email: EmailStr
    subject: str | None = Field(None, max_length=300)
    message: str = Field(..., max_length=5000)


class ReplyRequest(BaseModel):
    reply: str = Field(..., max_length=5000)


def _fmt(i: ContactInquiry) -> dict:
    return {
        "id":              i.id,
        "name":            i.name,
        "email":           i.email,
        "subject":         i.subject,
        "message":         i.message,
        "is_read":         i.is_read,
        "created_at":      i.created_at.isoformat(),
        "student_user_id": i.student_user_id,
        "osfa_reply":      i.osfa_reply,
        "replied_at":      i.replied_at.isoformat() if i.replied_at else None,
    }


@router.post("/api/contact", status_code=201)
@limiter.limit("5/minute")
async def submit_contact(
    request: Request,
    data: ContactRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    if not data.name.strip() or not data.message.strip():
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "Name and message are required"})

    inquiry = ContactInquiry(
        name=data.name.strip(),
        email=str(data.email),
        subject=data.subject.strip() if data.subject else None,
        message=data.message.strip(),
        student_user_id=current_user.id if current_user else None,
    )
    db.add(inquiry)
    await db.commit()

    # Email notification to OSFA
    notify_email = settings.SMTP_USER or settings.RESEND_FROM
    if notify_email:
        from app.utils.email import _send
        subject_line = data.subject.strip() if data.subject else "General Inquiry"
        safe_name = _html.escape(data.name.strip())
        safe_email = _html.escape(data.email)
        safe_subject = _html.escape(subject_line)
        safe_message = _html.escape(data.message.strip()).replace("\n", "<br>")
        asyncio.create_task(_send(
            notify_email,
            f"[IskoMo Contact] {subject_line} — from {data.name.strip()}",
            f"""<div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:32px;">
            <h2 style="color:#800000;">New Contact Inquiry</h2>
            <table style="width:100%;border-collapse:collapse;font-size:14px;">
              <tr><td style="padding:8px 0;color:#6b7280;width:100px;">From</td><td style="padding:8px 0;font-weight:600;">{safe_name}</td></tr>
              <tr><td style="padding:8px 0;color:#6b7280;">Email</td><td style="padding:8px 0;"><a href="mailto:{safe_email}">{safe_email}</a></td></tr>
              <tr><td style="padding:8px 0;color:#6b7280;">Subject</td><td style="padding:8px 0;">{safe_subject}</td></tr>
            </table>
            <div style="margin-top:16px;padding:16px;background:#f9fafb;border-radius:8px;border:1px solid #e5e7eb;">
              <p style="margin:0;font-size:14px;color:#111827;line-height:1.7;">{safe_message}</p>
            </div>
            </div>"""
        ))

    return {"message": "Inquiry submitted. We will respond within 3–5 business days.", "id": inquiry.id}


# ── OSFA access (all OSFA staff + admin) ──────────────────────────────────────

@router.get("/api/osfa/contacts")
async def osfa_list_contacts(
    page: int = 1,
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_osfa_or_admin),
):
    total = (await db.execute(select(func.count(ContactInquiry.id)))).scalar()
    items = (await db.execute(
        select(ContactInquiry).order_by(ContactInquiry.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {"total": total, "page": page, "items": [_fmt(i) for i in items]}


@router.patch("/api/osfa/contacts/{contact_id}/read", status_code=200)
async def osfa_mark_read(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_osfa_or_admin),
):
    inquiry = (await db.execute(select(ContactInquiry).where(ContactInquiry.id == contact_id))).scalar_one_or_none()
    if not inquiry:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Inquiry not found"})
    inquiry.is_read = True
    await db.commit()
    return _fmt(inquiry)


@router.post("/api/osfa/contacts/{contact_id}/reply", status_code=200)
async def osfa_reply(
    contact_id: int,
    data: ReplyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_osfa_or_admin),
):
    inquiry = (await db.execute(select(ContactInquiry).where(ContactInquiry.id == contact_id))).scalar_one_or_none()
    if not inquiry:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Inquiry not found"})

    inquiry.osfa_reply = data.reply.strip()
    inquiry.replied_at = datetime.now(timezone.utc)
    inquiry.is_read = True
    await db.commit()

    # In-app notification to student (works even if email fails)
    if inquiry.student_user_id:
        try:
            from app.services.notification_service import create_notification
            subject_preview = inquiry.subject or "your inquiry"
            await create_notification(
                db, inquiry.student_user_id,
                "OSFA Replied to Your Inquiry",
                f"OSFA has responded to your message: \"{subject_preview}\". Check the Contact OSFA page to view the reply.",
            )
        except Exception:
            pass

    # Email reply to student
    from app.utils.email import _send
    safe_inquiry_name = _html.escape(str(inquiry.name))
    safe_reply = _html.escape(data.reply.strip()).replace("\n", "<br>")
    asyncio.create_task(_send(
        inquiry.email,
        f"Re: {inquiry.subject or 'Your inquiry to IskoMo OSFA'}",
        f"""<div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:32px;">
        <h2 style="color:#800000;">Response from OSFA</h2>
        <p style="font-size:14px;color:#374151;">Hi {safe_inquiry_name},</p>
        <div style="padding:16px;background:#f9fafb;border-radius:8px;border:1px solid #e5e7eb;margin:16px 0;">
          <p style="margin:0;font-size:14px;color:#111827;line-height:1.7;">{safe_reply}</p>
        </div>
        <p style="font-size:12px;color:#9ca3af;">— IskoMo OSFA Team</p>
        </div>"""
    ))

    return _fmt(inquiry)


# ── Student: view own contact inquiries and OSFA replies ──────────────────────

@router.get("/api/student/contacts")
async def student_list_contacts(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = (await db.execute(
        select(ContactInquiry)
        .where(ContactInquiry.student_user_id == current_user.id)
        .order_by(ContactInquiry.created_at.desc())
    )).scalars().all()
    return {"items": [_fmt(i) for i in items]}


# ── Admin access (super_admin only) ───────────────────────────────────────────

@router.get("/api/admin/contacts")
async def list_contacts(
    page: int = 1,
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    total = (await db.execute(select(func.count(ContactInquiry.id)))).scalar()
    items = (await db.execute(
        select(ContactInquiry).order_by(ContactInquiry.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {"total": total, "page": page, "items": [_fmt(i) for i in items]}


@router.patch("/api/admin/contacts/{contact_id}/read", status_code=200)
async def mark_contact_read(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    inquiry = (await db.execute(select(ContactInquiry).where(ContactInquiry.id == contact_id))).scalar_one_or_none()
    if not inquiry:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Inquiry not found"})
    inquiry.is_read = True
    await db.commit()
    return _fmt(inquiry)
