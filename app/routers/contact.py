from fastapi import APIRouter, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

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
