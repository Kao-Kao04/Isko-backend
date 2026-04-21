from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update

from app.models.notification import Notification
from app.exceptions import NotFoundError


async def create_notification(
    db: AsyncSession,
    user_id: int,
    title: str,
    body: str,
    application_id: int | None = None,
) -> Notification:
    notif = Notification(user_id=user_id, title=title, body=body, application_id=application_id)
    db.add(notif)
    await db.flush()
    return notif


async def list_notifications(db: AsyncSession, user_id: int, page: int, page_size: int):
    q = select(Notification).where(Notification.user_id == user_id).order_by(Notification.created_at.desc())
    count_result = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_result.scalar()
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    return result.scalars().all(), total


async def mark_read(db: AsyncSession, user_id: int, notification_id: int) -> Notification:
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise NotFoundError("Notification", notification_id)
    notif.is_read = True
    await db.commit()
    await db.refresh(notif)
    return notif


async def mark_all_read(db: AsyncSession, user_id: int) -> None:
    await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read == False)
        .values(is_read=True)
    )
    await db.commit()


async def dismiss(db: AsyncSession, user_id: int, notification_id: int) -> None:
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise NotFoundError("Notification", notification_id)
    await db.delete(notif)
    await db.commit()
