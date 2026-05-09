import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.dependencies import require_super_admin
from app.models.user import User, UserRole, DepartmentEnum, AccountStatus
from app.models.application import Application
from app.models.scholarship import Scholarship
from app.models.audit import AuditEntry
from app.models.notification import Notification
from app.schemas.admin import StaffCreate, StaffUpdate, StaffResponse
from app.utils.security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])


class ResetPasswordRequest(BaseModel):
    new_password: str

class BroadcastRequest(BaseModel):
    title: str
    body: str
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
    _: User = Depends(require_super_admin),
):
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")
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
    _: User = Depends(require_super_admin),
):
    result = await db.execute(
        select(User).where(User.id == staff_id, User.role == UserRole.osfa_staff)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Staff not found")
    if data.department is not None:
        user.department = DepartmentEnum(data.department)
    if data.is_active is not None:
        user.is_active = data.is_active
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
    _: User = Depends(require_super_admin),
):
    result = await db.execute(
        select(User).where(User.id == staff_id, User.role == UserRole.osfa_staff)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Staff not found")
    await db.delete(user)
    await db.commit()


@router.patch("/staff/{staff_id}/reset-password", status_code=200)
async def reset_staff_password(
    staff_id: int,
    data: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    result = await db.execute(
        select(User).where(User.id == staff_id, User.role == UserRole.osfa_staff)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Staff not found")
    user.hashed_password = hash_password(data.new_password)
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
            "total":      await count(select(func.count(Application.id))),
            "pending":    await count(select(func.count(Application.id)).where(Application.status == "pending")),
            "approved":   await count(select(func.count(Application.id)).where(Application.status == "approved")),
            "rejected":   await count(select(func.count(Application.id)).where(Application.status == "rejected")),
            "withdrawn":  await count(select(func.count(Application.id)).where(Application.status == "withdrawn")),
        },
    }


# ── Student management ───────────────────────────────────────────────────────

@router.get("/students")
async def list_students(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    account_status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    from sqlalchemy.orm import selectinload
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

    total = (await db.execute(count_query)).scalar()
    users = (await db.execute(query.offset((page - 1) * page_size).limit(page_size))).scalars().all()

    from app.utils.pagination import paginate
    from app.schemas.user import UserResponse
    return paginate(users, total, page, page_size)


# ── Audit logs ───────────────────────────────────────────────────────────────

@router.get("/audit")
async def get_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_super_admin),
):
    from sqlalchemy.orm import selectinload
    query = (
        select(AuditEntry)
        .options(selectinload(AuditEntry.actor), selectinload(AuditEntry.application))
        .order_by(AuditEntry.created_at.desc())
    )
    total = (await db.execute(select(func.count(AuditEntry.id)))).scalar()
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
    _: User = Depends(require_super_admin),
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


# ── Reports export ───────────────────────────────────────────────────────────

@router.get("/reports/export")
async def export_report(
    type: str = Query("students", pattern="^(students|applications|scholars)$"),
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
            .where(User.role == UserRole.student).order_by(User.created_at.desc())
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
            .order_by(Application.submitted_at.desc())
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
            .order_by(Scholar.created_at.desc())
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
