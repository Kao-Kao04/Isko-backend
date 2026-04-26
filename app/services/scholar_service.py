from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.scholar import Scholar, SemesterRecord
from app.schemas.scholar import ScholarStatusUpdate, SemesterRecordCreate, SemesterRecordUpdate
from app.exceptions import NotFoundError


async def get_scholars_by_student(db: AsyncSession, student_id: int) -> list[Scholar]:
    result = await db.execute(select(Scholar).where(Scholar.student_id == student_id))
    return list(result.scalars().all())


async def list_scholars(db: AsyncSession, page: int, page_size: int):
    q = select(Scholar)
    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_result.scalar()
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return result.scalars().all(), total


async def get_scholar(db: AsyncSession, scholar_id: int) -> Scholar:
    result = await db.execute(select(Scholar).where(Scholar.id == scholar_id))
    scholar = result.scalar_one_or_none()
    if not scholar:
        raise NotFoundError("Scholar", scholar_id)
    return scholar


async def update_scholar_status(db: AsyncSession, scholar_id: int, data: ScholarStatusUpdate) -> Scholar:
    scholar = await get_scholar(db, scholar_id)
    scholar.status = data.status
    if data.is_graduating is not None:
        scholar.is_graduating = data.is_graduating
    if data.expected_graduation is not None:
        scholar.expected_graduation = data.expected_graduation
    await db.commit()
    await db.refresh(scholar)
    return scholar


async def add_semester_record(db: AsyncSession, scholar_id: int, data: SemesterRecordCreate) -> SemesterRecord:
    await get_scholar(db, scholar_id)
    record = SemesterRecord(scholar_id=scholar_id, **data.model_dump())
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def update_semester_record(
    db: AsyncSession, scholar_id: int, record_id: int, data: SemesterRecordUpdate
) -> SemesterRecord:
    result = await db.execute(
        select(SemesterRecord).where(SemesterRecord.id == record_id, SemesterRecord.scholar_id == scholar_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        raise NotFoundError("SemesterRecord", record_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(record, field, value)
    await db.commit()
    await db.refresh(record)
    return record
