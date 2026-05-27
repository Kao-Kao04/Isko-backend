from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.scholarship import Scholarship, ScholarshipStatus

router = APIRouter(prefix="/api/public", tags=["public"])


@router.get("/stats")
async def get_public_stats(db: AsyncSession = Depends(get_db)):
    count = (
        await db.execute(
            select(func.count(Scholarship.id)).where(
                Scholarship.status == ScholarshipStatus.active
            )
        )
    ).scalar() or 0
    return {"active_scholarships": count}
