from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_osfa
from app.models.user import User
from app.services import report_service

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("/overview")
async def overview(current_user: User = Depends(require_osfa), db: AsyncSession = Depends(get_db)):
    return await report_service.get_overview(db, current_user)


@router.get("/scholarships")
async def scholarship_breakdown(current_user: User = Depends(require_osfa), db: AsyncSession = Depends(get_db)):
    return await report_service.get_scholarship_breakdown(db, current_user)


@router.get("/applications")
async def application_trends(current_user: User = Depends(require_osfa), db: AsyncSession = Depends(get_db)):
    return await report_service.get_application_trends(db, current_user)
