import asyncio
from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.config import settings
from app.database import get_db
from app.dependencies import require_super_admin
from app.models.message import ContactInquiry
from app.models.user import User

router = APIRouter(tags=["contact"])


class ContactRequest(BaseModel):
    name: str
    email: EmailStr
    subject: str | None = None
    message: str


@router.post("/api/contact", status_code=201)
async def submit_contact(data: ContactRequest, db: AsyncSession = Depends(get_db)):
    if not data.name.strip() or not data.message.strip():
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail={"code": "VALIDATION_ERROR", "message": "Name and message are required"})

    inquiry = ContactInquiry(
        name=data.name.strip(),
        email=str(data.email),
        subject=data.subject.strip() if data.subject else None,
        message=data.message.strip(),
    )
    db.add(inquiry)
    await db.commit()

    # Forward inquiry to OSFA inbox via email
    notify_email = settings.SMTP_USER or settings.RESEND_FROM
    if notify_email:
        from app.utils.email import _send
        subject_line = data.subject.strip() if data.subject else "General Inquiry"
        asyncio.create_task(_send(
            notify_email,
            f"[IskoMo Contact] {subject_line} — from {data.name.strip()}",
            f"""<div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:32px;">
            <h2 style="color:#800000;">New Contact Inquiry</h2>
            <table style="width:100%;border-collapse:collapse;font-size:14px;">
              <tr><td style="padding:8px 0;color:#6b7280;width:100px;">From</td><td style="padding:8px 0;font-weight:600;">{data.name.strip()}</td></tr>
              <tr><td style="padding:8px 0;color:#6b7280;">Email</td><td style="padding:8px 0;"><a href="mailto:{data.email}">{data.email}</a></td></tr>
              <tr><td style="padding:8px 0;color:#6b7280;">Subject</td><td style="padding:8px 0;">{subject_line}</td></tr>
            </table>
            <div style="margin-top:16px;padding:16px;background:#f9fafb;border-radius:8px;border:1px solid #e5e7eb;">
              <p style="margin:0;font-size:14px;color:#111827;line-height:1.7;">{data.message.strip().replace(chr(10), '<br>')}</p>
            </div>
            <p style="margin-top:20px;font-size:12px;color:#9ca3af;">
              Reply directly to <a href="mailto:{data.email}">{data.email}</a> to respond to this inquiry.
            </p>
            </div>"""
        ))

    return {"message": "Inquiry submitted. We will respond within 3–5 business days."}


@router.get("/api/admin/contacts")
async def list_contacts(
    page: int = 1,
    page_size: int = 50,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    total = (await db.execute(select(func.count(ContactInquiry.id)))).scalar()
    items = (await db.execute(
        select(ContactInquiry).order_by(ContactInquiry.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    return {
        "total": total,
        "page": page,
        "items": [
            {
                "id": i.id,
                "name": i.name,
                "email": i.email,
                "subject": i.subject,
                "message": i.message,
                "is_read": i.is_read,
                "created_at": i.created_at.isoformat(),
            }
            for i in items
        ],
    }


@router.patch("/api/admin/contacts/{contact_id}/read", status_code=200)
async def mark_contact_read(
    contact_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    inquiry = (await db.execute(select(ContactInquiry).where(ContactInquiry.id == contact_id))).scalar_one_or_none()
    if not inquiry:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Inquiry not found"})
    inquiry.is_read = True
    await db.commit()
    return {"message": "Marked as read"}
