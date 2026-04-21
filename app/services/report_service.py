from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case

from app.models.application import Application, ApplicationStatus
from app.models.scholarship import Scholarship
from app.models.scholar import Scholar


async def get_overview(db: AsyncSession) -> dict:
    status_counts = await db.execute(
        select(Application.status, func.count(Application.id).label("count"))
        .group_by(Application.status)
    )
    counts = {row.status: row.count for row in status_counts}

    total_scholars = await db.execute(select(func.count(Scholar.id)))
    active_scholarships = await db.execute(
        select(func.count(Scholarship.id)).where(Scholarship.status == "active")
    )

    return {
        "applications_by_status": counts,
        "total_scholars": total_scholars.scalar(),
        "active_scholarships": active_scholarships.scalar(),
    }


async def get_scholarship_breakdown(db: AsyncSession) -> list:
    result = await db.execute(
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
    return [row._asdict() for row in result]


async def get_application_trends(db: AsyncSession) -> list:
    result = await db.execute(
        select(
            func.date_trunc("day", Application.submitted_at).label("date"),
            Application.status,
            func.count(Application.id).label("count"),
        )
        .group_by("date", Application.status)
        .order_by("date")
    )
    return [row._asdict() for row in result]
