from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case

from app.models.application import Application, ApplicationStatus
from app.models.scholarship import Scholarship
from app.models.scholar import Scholar
from app.models.user import User, UserRole


async def get_overview(db: AsyncSession, current_user: User) -> dict:
    applications_q = select(Application.status, func.count(Application.id).label("count"))
    if current_user.role == UserRole.osfa_staff and current_user.department:
        applications_q = (
            applications_q
            .join(Scholarship, Application.scholarship_id == Scholarship.id)
            .where(Scholarship.category == current_user.department.value)
        )
    applications_q = applications_q.group_by(Application.status)
    status_counts = await db.execute(applications_q)
    counts = {row.status: row.count for row in status_counts}

    total_scholars = await db.execute(select(func.count(Scholar.id)))

    active_scholarships_q = select(func.count(Scholarship.id)).where(Scholarship.status == "active")
    if current_user.role == UserRole.osfa_staff and current_user.department:
        active_scholarships_q = active_scholarships_q.where(
            Scholarship.category == current_user.department.value
        )
    active_scholarships = await db.execute(active_scholarships_q)

    return {
        "applications_by_status": counts,
        "total_scholars": total_scholars.scalar(),
        "active_scholarships": active_scholarships.scalar(),
    }


async def get_scholarship_breakdown(db: AsyncSession, current_user: User) -> list:
    q = (
        select(
            Scholarship.id,
            Scholarship.name,
            Scholarship.slots,
            func.count(Application.id).label("total_applications"),
            func.sum(case((Application.status == ApplicationStatus.approved, 1), else_=0)).label("approved"),
            func.sum(case((Application.status == ApplicationStatus.pending, 1), else_=0)).label("pending"),
            func.sum(case((Application.status == ApplicationStatus.rejected, 1), else_=0)).label("rejected"),
        )
        .outerjoin(Application, Application.scholarship_id == Scholarship.id)
        .group_by(Scholarship.id, Scholarship.name, Scholarship.slots)
    )
    if current_user.role == UserRole.osfa_staff and current_user.department:
        q = q.where(Scholarship.category == current_user.department.value)
    result = await db.execute(q)
    return [row._asdict() for row in result]


async def get_application_trends(db: AsyncSession, current_user: User) -> list:
    q = (
        select(
            func.date_trunc("day", Application.submitted_at).label("date"),
            Application.status,
            func.count(Application.id).label("count"),
        )
        .group_by("date", Application.status)
        .order_by("date")
    )
    if current_user.role == UserRole.osfa_staff and current_user.department:
        q = (
            q.join(Scholarship, Application.scholarship_id == Scholarship.id)
            .where(Scholarship.category == current_user.department.value)
        )
    result = await db.execute(q)
    return [row._asdict() for row in result]
