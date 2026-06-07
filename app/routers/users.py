from fastapi import APIRouter, Depends, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

import logging

from app.database import get_db
from app.dependencies import get_current_user, require_osfa_or_admin, require_student
from app.models.user import User, UserRole, AccountStatus
from app.models.registration import RegistrationDocument
from app.schemas.user import UserResponse, UpdateProfileRequest, PatchProfileRequest
from app.schemas.common import PaginatedResponse
from app.utils.pagination import paginate
import asyncio
from app.utils.storage import get_signed_url
from app.exceptions import NotFoundError, ValidationError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/users", tags=["users"])


class RejectStudentRequest(BaseModel):
    remarks: str


_LOCKED_PROFILE_FIELDS = {"college", "program", "year_level"}


async def _send_email_bg(coro, to_email: str, user_id: int) -> None:
    """Run an account-status email in the background — SMTP latency must never block the HTTP response."""
    try:
        await coro
    except Exception as exc:
        logger.error("Failed to send account-status email to %s (user %s): %s", to_email, user_id, exc)


@router.patch("/me/profile", response_model=UserResponse)
async def patch_my_profile(
    data: PatchProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException as _HTTPException
    profile = current_user.student_profile
    if not profile:
        raise NotFoundError("StudentProfile", current_user.id)
    updates = data.model_dump(exclude_unset=True)
    # Block changes to academic fields once account is pending_verification or verified
    if current_user.account_status in (AccountStatus.pending_verification, AccountStatus.verified):
        locked = _LOCKED_PROFILE_FIELDS & updates.keys()
        if locked:
            raise _HTTPException(
                status_code=403,
                detail={"code": "FORBIDDEN", "message": f"Cannot modify {', '.join(sorted(locked))} after verification has started"},
            )
    for field, value in updates.items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_me(
    data: UpdateProfileRequest,
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    profile = current_user.student_profile
    if profile:
        # Students cannot self-report GWA — it must come from official records via OSFA/admin
        updates = {k: v for k, v in data.model_dump(exclude_unset=True).items() if k != "gwa"}
        for field, value in updates.items():
            setattr(profile, field, value)
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.get("", response_model=PaginatedResponse[UserResponse])
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    account_status: str | None = Query(None),
    filter: str | None = Query(None),
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.models.application import Application as _App
    query = (
        select(User)
        .options(selectinload(User.student_profile))
        .where(User.role == UserRole.student)
        .order_by(User.created_at.desc())
    )
    count_query = select(func.count(User.id)).where(User.role == UserRole.student)

    if account_status:
        try:
            status_enum = AccountStatus(account_status)
            query = query.where(User.account_status == status_enum)
            count_query = count_query.where(User.account_status == status_enum)
        except ValueError:
            pass

    if filter == "with_application":
        sub = select(_App.student_id).distinct()
        query = query.where(User.id.in_(sub))
        count_query = count_query.where(User.id.in_(sub))
    elif filter == "no_application":
        sub = select(_App.student_id).distinct()
        query = query.where(User.id.notin_(sub))
        count_query = count_query.where(User.id.notin_(sub))

    count_result = await db.execute(count_query)
    total = count_result.scalar()
    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    users = result.scalars().all()
    return paginate(users, total, page, page_size)


async def _get_student_or_404(db: AsyncSession, user_id: int) -> User:
    result = await db.execute(
        select(User)
        .options(selectinload(User.student_profile))
        .where(User.id == user_id, User.role == UserRole.student)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User", user_id)
    return user


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    return await _get_student_or_404(db, user_id)


@router.get("/{user_id}/registration-documents")
async def get_registration_documents(
    user_id: int,
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    await _get_student_or_404(db, user_id)
    result = await db.execute(
        select(RegistrationDocument).where(RegistrationDocument.user_id == user_id)
    )
    docs = result.scalars().all()
    urls = await asyncio.gather(*[get_signed_url(d.storage_path) for d in docs])
    return [
        {
            "id": d.id,
            "doc_type": d.doc_type,
            "filename": d.filename,
            "url": url,
            "uploaded_at": d.uploaded_at,
        }
        for d, url in zip(docs, urls)
    ]


@router.patch("/{user_id}/approve", response_model=UserResponse)
async def approve_student(
    user_id: int,
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_student_or_404(db, user_id)
    if user.account_status not in (AccountStatus.pending_verification, AccountStatus.rejected):
        raise ValidationError("Only students with pending or rejected status can be approved")
    user.account_status = AccountStatus.verified
    user.rejection_remarks = None
    # Cache before commit — after commit all ORM attributes expire and accessing
    # them in async context raises MissingGreenlet (caught silently, email never sent).
    _user_id = int(user.id)           # type: ignore[arg-type]
    _email   = str(user.email)
    await db.commit()

    try:
        from app.services.notification_service import create_notification
        await create_notification(
            db, _user_id,
            "Account Verified",
            "Your IskoMo account has been verified by OSFA. You can now apply for scholarships!",
        )
        await db.commit()
    except Exception:
        pass

    from app.utils.email import send_account_verified_email
    asyncio.create_task(_send_email_bg(send_account_verified_email(_email), _email, user_id))

    return await _get_student_or_404(db, user_id)


@router.patch("/{user_id}/reject", response_model=UserResponse)
async def reject_student(
    user_id: int,
    data: RejectStudentRequest,
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_student_or_404(db, user_id)
    if user.account_status != AccountStatus.pending_verification:
        raise ValidationError("Only students with pending_verification status can be rejected")
    user.account_status = AccountStatus.rejected
    user.rejection_remarks = data.remarks
    _user_id = int(user.id)   # type: ignore[arg-type]
    _email   = str(user.email)
    await db.commit()

    try:
        from app.services.notification_service import create_notification
        reason_text = f" Reason: {data.remarks}" if data.remarks else " Please contact OSFA for more information."
        await create_notification(
            db, _user_id,
            "Account Verification Rejected",
            f"Your IskoMo account verification was not approved.{reason_text}",
        )
        await db.commit()
    except Exception:
        pass

    from app.utils.email import send_account_rejected_email
    asyncio.create_task(_send_email_bg(send_account_rejected_email(_email, data.remarks), _email, user_id))

    return await _get_student_or_404(db, user_id)


@router.post("/send-registration-reminders", status_code=200)
async def send_registration_reminders(
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(
            User.role == UserRole.student,
            User.account_status == AccountStatus.unregistered,
        )
    )
    users = result.scalars().all()

    from app.utils.email import send_registration_reminder_email
    sent, failed = 0, 0
    for u in users:
        try:
            await send_registration_reminder_email(str(u.email))
            sent += 1
        except Exception:
            failed += 1

    return {"sent": sent, "failed": failed, "total": len(users)}


# ─── GWA Request endpoints ────────────────────────────────────────────────────

class GwaRejectRequest(BaseModel):
    remarks: str | None = None


@router.get("/{user_id}/gwa-proof")
async def get_gwa_proof(
    user_id: int,
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_student_or_404(db, user_id)
    p = user.student_profile
    if not p or not p.gwa_proof_path:
        raise NotFoundError("GWA proof", user_id)
    from app.utils.storage import get_signed_url
    url = await get_signed_url(str(p.gwa_proof_path))
    return {"url": url}


@router.post("/me/gwa-request", status_code=200)
async def submit_gwa_request(
    gwa: str = Form(...),
    proof: UploadFile = File(...),
    current_user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    p = current_user.student_profile
    if not p:
        raise ValidationError("Student profile not found")

    try:
        gwa_val = float(gwa.strip())
        if not (1.00 <= gwa_val <= 5.00):
            raise ValidationError("GWA must be between 1.00 and 5.00")
    except (ValueError, TypeError):
        raise ValidationError("GWA must be a valid number (e.g., 1.75)")

    content_type = proof.content_type or "application/octet-stream"
    if content_type not in ("image/jpeg", "image/png", "image/webp", "application/pdf"):
        raise ValidationError("Proof must be an image (JPG/PNG/WEBP) or PDF")

    from app.utils.storage import upload_file, delete_file
    file_bytes = await proof.read()
    if len(file_bytes) > 5 * 1024 * 1024:
        raise ValidationError("File must be under 5 MB")

    # Delete old proof if exists
    if p.gwa_proof_path:
        await delete_file(str(p.gwa_proof_path))

    path = await upload_file(file_bytes, proof.filename or "proof", content_type)
    _student_name = f"{p.first_name} {p.last_name}".strip()  # cache before commit
    p.pending_gwa           = gwa.strip()
    p.gwa_proof_path        = path
    p.gwa_request_status    = "pending"
    p.gwa_rejection_remarks = None
    await db.commit()

    # Notify OSFA
    try:
        from app.models.user import User as _User
        osfa_result = await db.execute(
            select(_User).where(_User.role == UserRole.osfa_staff, _User.is_active == True)
        )
        osfa_users = osfa_result.scalars().all()
        from app.services.notification_service import create_notification
        for staff in osfa_users:
            await create_notification(db, staff.id, "GWA Update Request",  # type: ignore[arg-type]
                f"{_student_name} submitted a GWA update request (GWA: {gwa.strip()}).",
                link="/registrations")
        await db.commit()
    except Exception:
        pass

    await db.refresh(current_user, ["student_profile"])
    from app.schemas.user import UserResponse
    return UserResponse.model_validate(current_user)


@router.patch("/{user_id}/gwa-request/approve", status_code=200)
async def approve_gwa_request(
    user_id: int,
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_student_or_404(db, user_id)
    p = user.student_profile
    if not p or p.gwa_request_status != "pending":
        raise ValidationError("No pending GWA request for this student")

    old_proof = p.gwa_proof_path
    _new_gwa = p.pending_gwa  # cache before commit expires ORM attrs
    p.gwa                   = p.pending_gwa
    p.pending_gwa           = None
    p.gwa_request_status    = "approved"
    p.gwa_rejection_remarks = None
    # Clear proof path only after successfully deleting the file so the DB
    # never points to a non-existent object if the delete fails mid-flight.
    if old_proof:
        from app.utils.storage import delete_file
        try:
            await delete_file(str(old_proof))
        except Exception:
            pass
    p.gwa_proof_path = None
    await db.commit()

    try:
        from app.services.notification_service import create_notification
        await create_notification(db, user.id, "GWA Update Approved",  # type: ignore[arg-type]
            f"Your GWA update to {_new_gwa} has been verified and approved by OSFA.",
            link="/profile")
        await db.commit()
    except Exception:
        pass

    return {"status": "approved", "gwa": _new_gwa}


@router.patch("/{user_id}/gwa-request/reject", status_code=200)
async def reject_gwa_request(
    user_id: int,
    data: GwaRejectRequest,
    _: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_student_or_404(db, user_id)
    p = user.student_profile
    if not p or p.gwa_request_status != "pending":
        raise ValidationError("No pending GWA request for this student")

    old_proof = p.gwa_proof_path
    p.gwa_request_status    = "rejected"
    p.gwa_rejection_remarks = data.remarks
    p.pending_gwa           = None
    p.gwa_proof_path        = None
    if old_proof:
        from app.utils.storage import delete_file
        try:
            await delete_file(str(old_proof))
        except Exception:
            pass
    await db.commit()

    try:
        from app.services.notification_service import create_notification
        reason = f" Reason: {data.remarks}" if data.remarks else ""
        await create_notification(db, user.id, "GWA Update Rejected",  # type: ignore[arg-type]
            f"Your GWA update request was not approved by OSFA.{reason}",
            link="/profile")
        await db.commit()
    except Exception:
        pass

    return {"status": "rejected"}
