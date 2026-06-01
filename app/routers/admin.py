import csv
import io
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.dependencies import require_super_admin
from app.models.user import User, UserRole, DepartmentEnum, AccountStatus
from app.models.application import Application
from app.models.scholar import Scholar, ScholarStatus
from app.models.workflow import MainStatus
from app.models.scholarship import Scholarship
from app.models.audit import AuditEntry
from app.models.notification import Notification
from app.schemas.admin import StaffCreate, StaffUpdate, StaffResponse
from app.utils.security import hash_password
from app.utils.audit import log_system_audit
from app.exceptions import ConflictError, NotFoundError, ValidationError

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ResetPasswordRequest(BaseModel):
    new_password: str

class BroadcastRequest(BaseModel):
    title: str = Field(..., max_length=200)
    body: str = Field(..., max_length=2000)
    target: str = "students"  # "students" | "osfa_staff" | "all"


# ── Staff CRUD ──────────────────────────────────────────────────────────────

@router.get("/staff", response_model=list[StaffResponse])
async def list_staff(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    result = await db.execute(
        select(User).where(User.role == UserRole.osfa_staff).order_by(User.created_at.desc())
    )
    staff = result.scalars().all()
    return [StaffResponse(
        id=s.id, email=s.email,
        department=s.department.value if s.department else None,
        is_active=s.is_active, created_at=s.created_at.isoformat(),
    ) for s in staff]


@router.post("/staff", response_model=StaffResponse, status_code=201)
async def create_staff(
    data: StaffCreate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise ConflictError("Email already registered")
    user = User(
        email=data.email,
        hashed_password=hash_password(data.password),
        role=UserRole.osfa_staff,
        department=DepartmentEnum(data.department),
        is_verified=True,
        account_status=AccountStatus.approved,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await log_system_audit(db, actor.id, "user", "create_staff", entity_id=user.id,
                           after_state={"email": user.email, "department": data.department})
    await db.commit()
    await db.refresh(user)
    return StaffResponse(
        id=user.id, email=user.email,
        department=user.department.value if user.department else None,
        is_active=user.is_active, created_at=user.created_at.isoformat(),
    )


@router.patch("/staff/{staff_id}", response_model=StaffResponse)
async def update_staff(
    staff_id: int,
    data: StaffUpdate,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    result = await db.execute(
        select(User).where(User.id == staff_id, User.role == UserRole.osfa_staff)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("Staff", staff_id)
    before = {"department": user.department.value if user.department else None, "is_active": user.is_active}
    if data.department is not None:
        user.department = DepartmentEnum(data.department)
    if data.is_active is not None:
        user.is_active = data.is_active
    after = {"department": user.department.value if user.department else None, "is_active": user.is_active}
    await log_system_audit(db, actor.id, "user", "update_staff", entity_id=staff_id,
                           before_state=before, after_state=after)
    await db.commit()
    await db.refresh(user)
    return StaffResponse(
        id=user.id, email=user.email,
        department=user.department.value if user.department else None,
        is_active=user.is_active, created_at=user.created_at.isoformat(),
    )


@router.delete("/staff/{staff_id}", status_code=204)
async def delete_staff(
    staff_id: int,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    result = await db.execute(
        select(User).where(User.id == staff_id, User.role == UserRole.osfa_staff)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("Staff", staff_id)
    await log_system_audit(db, actor.id, "user", "delete_staff", entity_id=staff_id,
                           before_state={"email": user.email, "department": user.department.value if user.department else None})
    await db.delete(user)
    await db.commit()


@router.patch("/staff/{staff_id}/reset-password", status_code=200)
async def reset_staff_password(
    staff_id: int,
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    if len(data.new_password) < 8:
        raise ValidationError("Password must be at least 8 characters")
    result = await db.execute(
        select(User).where(User.id == staff_id, User.role == UserRole.osfa_staff)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("Staff", staff_id)
    user.hashed_password = hash_password(data.new_password)
    await log_system_audit(db, actor.id, "user", "reset_staff_password", entity_id=staff_id)
    await db.commit()
    return {"message": "Password reset successfully"}


# ── Dashboard stats ──────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    async def count(query): return (await db.execute(query)).scalar()

    return {
        "students": {
            "total":               await count(select(func.count(User.id)).where(User.role == UserRole.student)),
            "pending_verification":await count(select(func.count(User.id)).where(User.role == UserRole.student, User.account_status == AccountStatus.pending_verification)),
            "verified":            await count(select(func.count(User.id)).where(User.role == UserRole.student, User.account_status == AccountStatus.verified)),
            "rejected":            await count(select(func.count(User.id)).where(User.role == UserRole.student, User.account_status == AccountStatus.rejected)),
            "unregistered":        await count(select(func.count(User.id)).where(User.role == UserRole.student, User.account_status == AccountStatus.unregistered)),
            "scholars":            await count(select(func.count(Scholar.student_id.distinct())).where(
                Scholar.status.in_([
                    ScholarStatus.active, ScholarStatus.probationary,
                    ScholarStatus.under_review, ScholarStatus.on_leave, ScholarStatus.suspended,
                ])
            )),
        },
        "staff": {
            "total":  await count(select(func.count(User.id)).where(User.role == UserRole.osfa_staff)),
            "active": await count(select(func.count(User.id)).where(User.role == UserRole.osfa_staff, User.is_active == True)),
        },
        "scholarships": {
            "total":    await count(select(func.count(Scholarship.id))),
            "active":   await count(select(func.count(Scholarship.id)).where(Scholarship.status == "active")),
            "draft":    await count(select(func.count(Scholarship.id)).where(Scholarship.status == "draft")),
            "archived": await count(select(func.count(Scholarship.id)).where(Scholarship.status == "archived")),
        },
        "applications": {
            "total":       await count(select(func.count(Application.id))),
            "in_progress": await count(select(func.count(Application.id)).where(
                Application.main_status.in_([
                    MainStatus.APPLICATION, MainStatus.VERIFICATION,
                    MainStatus.INTERVIEW, MainStatus.DECISION,
                ])
            )),
            "approved":    await count(select(func.count(Application.id)).where(
                Application.main_status == MainStatus.COMPLETION
            )),
            "rejected":    await count(select(func.count(Application.id)).where(
                Application.main_status == MainStatus.REJECTED
            )),
            "withdrawn":   await count(select(func.count(Application.id)).where(
                Application.main_status == MainStatus.WITHDRAWN
            )),
        },
    }


# ── Student management ───────────────────────────────────────────────────────

@router.get("/students")
async def list_students(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    account_status: str | None = Query(None),
    scholar_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    from sqlalchemy.orm import selectinload
    from app.models.scholar import Scholar as ScholarModel
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

    if scholar_only:
        scholar_subq = select(ScholarModel.student_id).distinct().subquery()
        query = query.where(User.id.in_(select(scholar_subq.c.student_id)))
        count_query = count_query.where(User.id.in_(select(scholar_subq.c.student_id)))

    total = (await db.execute(count_query)).scalar()
    users = (await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all()

    # Attach scholar status — prefer active/probationary over terminal statuses
    from app.schemas.user import UserResponse
    user_ids = [u.id for u in users]
    scholar_map: dict[int, str] = {}
    if user_ids:
        _STATUS_RANK = {
            'active': 0, 'probationary': 1, 'under_review': 2,
            'on_leave': 3, 'suspended': 4, 'graduated': 5, 'terminated': 6,
        }
        rows = (await db.execute(
            select(ScholarModel.student_id, ScholarModel.status).where(ScholarModel.student_id.in_(user_ids))
        )).all()
        for sid, sstat in rows:
            sv = sstat.value
            existing = scholar_map.get(sid)
            if existing is None or _STATUS_RANK.get(sv, 99) < _STATUS_RANK.get(existing, 99):
                scholar_map[sid] = sv

    items = []
    for u in users:
        d = UserResponse.model_validate(u).model_dump()
        d['scholar_status'] = scholar_map.get(u.id)  # type: ignore[arg-type]
        items.append(d)

    total_count = int(total or 0)
    pages = (total_count + page_size - 1) // page_size if page_size else 1
    return {"items": items, "total": total_count, "page": page, "page_size": page_size, "pages": pages}


@router.patch("/students/{student_id}/toggle-active", status_code=200)
async def toggle_student_active(
    student_id: int,
    actor: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.id == student_id, User.role == UserRole.student)
    )
    user = result.scalar_one_or_none()
    if not user:
        from app.exceptions import NotFoundError
        raise NotFoundError("Student", student_id)
    _was_active = bool(user.is_active)   # cache before commit — attrs expire after commit
    user.is_active = not _was_active  # type: ignore[assignment]
    await db.commit()
    _now_active = not _was_active
    action = "reactivate_student" if _now_active else "deactivate_student"
    await log_system_audit(db, actor.id, "user", action, entity_id=student_id,
                           before_state={"is_active": _was_active},
                           after_state={"is_active": _now_active})
    return {"id": student_id, "is_active": _now_active,
            "message": f"Account {'reactivated' if _now_active else 'deactivated'} successfully."}


@router.delete("/students/{student_id}", status_code=204)
async def delete_student(
    student_id: int,
    actor: User = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.id == student_id, User.role == UserRole.student)
    )
    user = result.scalar_one_or_none()
    if not user:
        from app.exceptions import NotFoundError
        raise NotFoundError("Student", student_id)

    # Block deletion if the student has non-withdrawn applications
    from app.models.application import Application, ApplicationStatus
    from app.exceptions import ValidationError
    app_count = (await db.execute(
        select(func.count(Application.id)).where(
            Application.student_id == student_id,
            Application.status.notin_([ApplicationStatus.withdrawn]),
        )
    )).scalar()
    if app_count > 0:
        raise ValidationError(
            f"Cannot delete this student — they have {app_count} active application(s). "
            "Deactivate the account instead."
        )

    await log_system_audit(db, actor.id, "user", "delete_student", entity_id=student_id,
                           before_state={"email": user.email}, after_state=None)
    await db.delete(user)
    await db.commit()


# ── Audit logs ───────────────────────────────────────────────────────────────

@router.get("/audit")
async def get_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    from sqlalchemy.orm import selectinload
    base = select(AuditEntry)
    if date_from:
        base = base.where(AuditEntry.created_at >= datetime(date_from.year, date_from.month, date_from.day, tzinfo=timezone.utc))
    if date_to:
        next_day = datetime(date_to.year, date_to.month, date_to.day, tzinfo=timezone.utc) + timedelta(days=1)
        base = base.where(AuditEntry.created_at < next_day)
    query = base.options(selectinload(AuditEntry.actor), selectinload(AuditEntry.application)).order_by(AuditEntry.created_at.desc())
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar()
    entries = (await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all()

    return {
        "total": total,
        "page": page,
        "items": [
            {
                "id": e.id,
                "application_id": e.application_id,
                "actor_email": e.actor.email if e.actor else "—",
                "action": e.action,
                "from_status": e.from_status,
                "to_status": e.to_status,
                "note": e.note,
                "created_at": e.created_at.isoformat(),
            }
            for e in entries
        ],
    }


# ── Broadcast notification ───────────────────────────────────────────────────

@router.post("/broadcast", status_code=201)
async def broadcast_notification(
    data: BroadcastRequest,
    db: AsyncSession = Depends(get_db),
    actor: User = Depends(require_super_admin),
):
    if data.target == "students":
        role_filter = UserRole.student
    elif data.target == "osfa_staff":
        role_filter = UserRole.osfa_staff
    else:
        role_filter = None

    query = select(User).where(User.is_active == True)
    if role_filter:
        query = query.where(User.role == role_filter)

    users = (await db.execute(query)).scalars().all()

    notifications = [
        Notification(user_id=u.id, title=data.title, body=data.body)
        for u in users
    ]
    db.add_all(notifications)
    await log_system_audit(db, actor.id, "broadcast", "broadcast_notification",
                           after_state={"title": data.title, "target": data.target, "recipient_count": len(notifications)})
    await db.commit()

    from app.websocket import manager
    import asyncio
    for u in users:
        asyncio.create_task(manager.send(u.id, {
            "type": "notification",
            "title": data.title,
            "body": data.body,
        }))

    return {"message": f"Notification sent to {len(notifications)} users."}


# ── One-time backfill: resend account-verified emails ────────────────────────

@router.post("/backfill/resend-verification-emails", status_code=200)
async def backfill_verification_emails(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    """Send account-verified email to all students who were approved but never
    received the email (due to a MissingGreenlet bug, now fixed)."""
    from app.utils.email import send_account_verified_email

    verified_students = (await db.execute(
        select(User).where(
            User.role == UserRole.student,
            User.account_status == AccountStatus.verified,
            User.is_active == True,
        )
    )).scalars().all()

    sent, failed, errors = 0, 0, []
    for u in verified_students:
        _email = str(u.email)
        try:
            await send_account_verified_email(_email)
            sent += 1
        except Exception as exc:
            failed += 1
            errors.append({"email": _email, "error": str(exc)})

    return {
        "total":  len(verified_students),
        "sent":   sent,
        "failed": failed,
        "errors": errors,
    }


# ── Reports export ───────────────────────────────────────────────────────────

@router.get("/reports/export")
async def export_report(
    type: str = Query("students", pattern="^(students|applications|scholars)$"),
    limit: int = Query(5000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    from sqlalchemy.orm import selectinload

    output = io.StringIO()
    writer = csv.writer(output)

    if type == "students":
        writer.writerow(["ID", "Email", "Student Number", "First Name", "Last Name", "College", "Program", "Year Level", "GWA", "Account Status", "Registered At"])
        users = (await db.execute(
            select(User).options(selectinload(User.student_profile))
            .where(User.role == UserRole.student).order_by(User.created_at.desc()).limit(limit)
        )).scalars().all()
        for u in users:
            p = u.student_profile
            writer.writerow([
                u.id, u.email,
                p.student_number if p else "", p.first_name if p else "", p.last_name if p else "",
                p.college if p else "", p.program if p else "", p.year_level if p else "", p.gwa if p else "",
                u.account_status.value, u.created_at.strftime("%Y-%m-%d %H:%M"),
            ])

    elif type == "applications":
        writer.writerow(["ID", "Student Email", "Student Number", "Scholarship", "Status", "Submitted At"])
        from app.models.scholarship import Scholarship
        apps = (await db.execute(
            select(Application)
            .options(selectinload(Application.student).selectinload(User.student_profile), selectinload(Application.scholarship))
            .order_by(Application.submitted_at.desc()).limit(limit)
        )).scalars().all()
        for a in apps:
            p = a.student.student_profile if a.student else None
            writer.writerow([
                a.id, a.student.email if a.student else "",
                p.student_number if p else "",
                a.scholarship.name if a.scholarship else "",
                a.status, a.submitted_at.strftime("%Y-%m-%d %H:%M"),
            ])

    elif type == "scholars":
        from app.models.scholar import Scholar
        writer.writerow(["ID", "Student Email", "Student Number", "Scholarship", "Status", "Start Date"])
        scholars = (await db.execute(
            select(Scholar)
            .options(selectinload(Scholar.user).selectinload(User.student_profile), selectinload(Scholar.scholarship))
            .order_by(Scholar.created_at.desc()).limit(limit)
        )).scalars().all()
        for s in scholars:
            p = s.user.student_profile if s.user else None
            writer.writerow([
                s.id, s.user.email if s.user else "",
                p.student_number if p else "",
                s.scholarship.name if s.scholarship else "",
                s.status, s.created_at.strftime("%Y-%m-%d"),
            ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={type}-report.csv"},
    )
