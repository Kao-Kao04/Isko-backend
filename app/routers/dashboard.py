from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.dependencies import require_osfa_or_admin
from app.models.user import User, UserRole
from app.models.application import Application, ApplicationStatus
from app.models.scholarship import Scholarship, ScholarshipStatus
from app.models.scholar import Scholar, ScholarStatus

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/stats")
async def dashboard_stats(
    current_user: User = Depends(require_osfa_or_admin),
    db: AsyncSession = Depends(get_db),
):
    dept_filter = (
        current_user.role == UserRole.osfa_staff and current_user.department
    )

    def _app_count(status: ApplicationStatus | None = None):
        q = select(func.count(Application.id))
        if dept_filter:
            q = q.join(Scholarship, Application.scholarship_id == Scholarship.id).where(
                Scholarship.category == current_user.department.value
            )
        if status:
            q = q.where(Application.status == status)
        return q

    total_q   = _app_count()
    pending_q = _app_count(ApplicationStatus.pending)
    approved_q = _app_count(ApplicationStatus.approved)
    rejected_q = _app_count(ApplicationStatus.rejected)

    scholars_q = select(func.count(Scholar.id)).where(
        Scholar.status == ScholarStatus.active
    )
    if dept_filter:
        scholars_q = scholars_q.join(
            Scholarship, Scholar.scholarship_id == Scholarship.id
        ).where(Scholarship.category == current_user.department.value)

    active_scholarships_q = select(func.count(Scholarship.id)).where(
        Scholarship.status == ScholarshipStatus.active
    )
    if dept_filter:
        active_scholarships_q = active_scholarships_q.where(
            Scholarship.category == current_user.department.value
        )

    total        = (await db.execute(total_q)).scalar() or 0
    pending      = (await db.execute(pending_q)).scalar() or 0
    approved     = (await db.execute(approved_q)).scalar() or 0
    rejected     = (await db.execute(rejected_q)).scalar() or 0
    total_scholars      = (await db.execute(scholars_q)).scalar() or 0
    active_scholarships = (await db.execute(active_scholarships_q)).scalar() or 0

    return {
        "total_applications": total,
        "pending": pending,
        "approved": approved,
        "rejected": rejected,
        "active_scholarships": active_scholarships,
        "total_scholars": total_scholars,
    }
