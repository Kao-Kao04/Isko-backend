import csv
import io
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import require_osfa_or_admin
from app.models.user import User, UserRole
from app.models.application import Application
from app.models.scholarship import Scholarship
from app.models.workflow import SubStatus
from app.services import report_service

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/overview")
async def overview(current_user: User = Depends(require_osfa_or_admin), db: AsyncSession = Depends(get_db)):
    return await report_service.get_overview(db, current_user)


@router.get("/scholarships")
async def scholarship_breakdown(current_user: User = Depends(require_osfa_or_admin), db: AsyncSession = Depends(get_db)):
    return await report_service.get_scholarship_breakdown(db, current_user)


@router.get("/applications")
async def application_trends(current_user: User = Depends(require_osfa_or_admin), db: AsyncSession = Depends(get_db)):
    return await report_service.get_application_trends(db, current_user)


@router.get("/export/applications")
async def export_applications_csv(
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Download all applications (filtered by dept for osfa_staff) as CSV."""
    q = (
        select(Application)
        .options(
            selectinload(Application.student).selectinload(User.student_profile),
            selectinload(Application.scholarship),
        )
        .order_by(Application.submitted_at.desc())
    )
    if current_user.role == UserRole.osfa_staff and current_user.department:
        q = q.join(Scholarship, Application.scholarship_id == Scholarship.id).where(
            Scholarship.category == current_user.department.value
        )
    apps = (await db.execute(q)).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Student Name", "Student Number", "Email", "Scholarship", "Status", "Workflow Stage", "Submitted At"])
    for a in apps:
        p = a.student.student_profile if a.student else None
        name = f"{p.first_name} {p.last_name}".strip() if p else f"Student #{a.student_id}"
        writer.writerow([
            a.id, name,
            p.student_number if p else "",
            a.student.email if a.student else "",
            a.scholarship.name if a.scholarship else "",
            a.status.value if hasattr(a.status, "value") else str(a.status),
            f"{a.main_status}/{a.sub_status}" if a.main_status else "pre-workflow",
            a.submitted_at.strftime("%Y-%m-%d %H:%M") if a.submitted_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=applications-export.csv"},
    )


@router.get("/export/scholars")
async def export_scholars_csv(
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Download all scholars (filtered by dept) as CSV."""
    from app.models.scholar import Scholar
    from sqlalchemy.orm import selectinload as sil
    q = (
        select(Scholar)
        .options(
            sil(Scholar.user).selectinload(User.student_profile),
            sil(Scholar.scholarship),
        )
        .order_by(Scholar.created_at.desc())
    )
    if current_user.role == UserRole.osfa_staff and current_user.department:
        q = q.join(Scholarship, Scholar.scholarship_id == Scholarship.id).where(
            Scholarship.category == current_user.department.value
        )
    scholars = (await db.execute(q)).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Student Name", "Student Number", "Email", "Scholarship", "Scholar Status", "Allowance Status", "Start Date"])
    for s in scholars:
        p = s.user.student_profile if s.user else None
        name = f"{p.first_name} {p.last_name}".strip() if p else f"Student #{s.student_id}"
        writer.writerow([
            s.id, name,
            p.student_number if p else "",
            s.user.email if s.user else "",
            s.scholarship.name if s.scholarship else "",
            s.status.value if hasattr(s.status, "value") else str(s.status),
            s.allowance_status or "pending",
            s.created_at.strftime("%Y-%m-%d") if s.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=scholars-export.csv"},
    )


@router.get("/calendar")
async def interview_calendar(
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return all scheduled interviews for the calendar view."""
    q = (
        select(Application)
        .options(
            selectinload(Application.student).selectinload(User.student_profile),
            selectinload(Application.scholarship),
        )
        .where(
            Application.interview_datetime.isnot(None),
            Application.sub_status == SubStatus.SCHEDULED,
        )
        .order_by(Application.interview_datetime)
    )
    if current_user.role == UserRole.osfa_staff and current_user.department:
        q = q.join(Scholarship, Application.scholarship_id == Scholarship.id).where(
            Scholarship.category == current_user.department.value
        )
    apps = (await db.execute(q)).scalars().all()

    events = []
    for a in apps:
        p = a.student.student_profile if a.student else None
        name = f"{p.first_name} {p.last_name}".strip() if p else f"Student #{a.student_id}"
        events.append({
            "application_id": a.id,
            "student_name": name,
            "scholarship_name": a.scholarship.name if a.scholarship else "",
            "interview_datetime": a.interview_datetime.isoformat() if a.interview_datetime else None,
            "interview_location": a.interview_location,
        })
    return {"events": events}
