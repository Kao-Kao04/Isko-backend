from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case

from app.models.application import Application
from app.models.workflow import MainStatus, SubStatus
from app.models.scholarship import Scholarship
from app.models.scholar import Scholar, ScholarStatus
from app.models.user import User, UserRole


def _dept_filter(q, user: User):
    if user.role == UserRole.osfa_staff and user.department:
        return (
            q.join(Scholarship, Application.scholarship_id == Scholarship.id)
            .where(Scholarship.category == user.department.value)
        )
    return q


async def get_overview(db: AsyncSession, current_user: User) -> dict:
    # Base query using main_status — accurate regardless of legacy status drift
    base = select(Application.main_status, func.count(Application.id).label("count"))
    base = _dept_filter(base, current_user).group_by(Application.main_status)
    rows = (await db.execute(base)).all()
    by_main = {row.main_status: row.count for row in rows}

    # Map main_status buckets to dashboard-friendly labels
    in_progress = sum(
        v for k, v in by_main.items()
        if k in (MainStatus.APPLICATION, MainStatus.VERIFICATION,
                 MainStatus.INTERVIEW, MainStatus.DECISION)
    )
    approved  = by_main.get(MainStatus.COMPLETION, 0)
    rejected  = by_main.get(MainStatus.REJECTED, 0)
    withdrawn = by_main.get(MainStatus.WITHDRAWN, 0)

    # sub-status breakdown for DECISION stage
    decision_q = select(Application.sub_status, func.count(Application.id).label("count"))
    decision_q = _dept_filter(
        decision_q.where(Application.main_status == MainStatus.DECISION), current_user
    ).group_by(Application.sub_status)
    decision_rows = (await db.execute(decision_q)).all()
    decision_by_sub = {row.sub_status: row.count for row in decision_rows}

    total_scholars_q = select(func.count(Scholar.id)).where(Scholar.status == ScholarStatus.active)
    active_scholarships_q = select(func.count(Scholarship.id)).where(Scholarship.status == "active")
    if current_user.role == UserRole.osfa_staff and current_user.department:
        active_scholarships_q = active_scholarships_q.where(
            Scholarship.category == current_user.department.value
        )

    return {
        "applications_by_status": {
            "in_progress": in_progress,
            "approved":    approved,
            "rejected":    rejected,
            "withdrawn":   withdrawn,
            "waitlisted":  decision_by_sub.get(SubStatus.WAITLISTED, 0),
        },
        "total_scholars": (await db.execute(total_scholars_q)).scalar(),
        "active_scholarships": (await db.execute(active_scholarships_q)).scalar(),
    }


async def get_scholarship_breakdown(db: AsyncSession, current_user: User) -> list:
    q = (
        select(
            Scholarship.id,
            Scholarship.name,
            Scholarship.slots,
            func.count(Application.id).label("total_applications"),
            func.sum(case(
                (Application.main_status == MainStatus.COMPLETION, 1), else_=0
            )).label("approved"),
            func.sum(case(
                (Application.main_status.in_([
                    MainStatus.APPLICATION, MainStatus.VERIFICATION,
                    MainStatus.INTERVIEW, MainStatus.DECISION,
                ]), 1), else_=0
            )).label("in_progress"),
            func.sum(case(
                (Application.main_status == MainStatus.REJECTED, 1), else_=0
            )).label("rejected"),
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
            Application.main_status,
            func.count(Application.id).label("count"),
        )
        .group_by("date", Application.main_status)
        .order_by("date")
    )
    if current_user.role == UserRole.osfa_staff and current_user.department:
        q = (
            q.join(Scholarship, Application.scholarship_id == Scholarship.id)
            .where(Scholarship.category == current_user.department.value)
        )
    result = await db.execute(q)
    return [row._asdict() for row in result]
