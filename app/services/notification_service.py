from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, update, insert

from app.models.notification import Notification
from app.models.user import User, UserRole
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

    from app.websocket import manager
    await manager.send(user_id, {
        "type": "notification",
        "id": notif.id,
        "title": title,
        "body": body,
        "application_id": application_id,
    })
    return notif


async def broadcast_announcement(db: AsyncSession, title: str, body: str) -> int:
    # Get only IDs — avoids loading full User objects into memory
    id_result = await db.execute(
        select(User.id).where(User.role == UserRole.student, User.is_active == True)
    )
    student_ids = id_result.scalars().all()
    if not student_ids:
        return 0

    await db.execute(
        insert(Notification),
        [{"user_id": uid, "title": title, "body": body} for uid in student_ids],
    )
    await db.commit()
    return len(student_ids)


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


async def send_announcement(
    db: AsyncSession,
    title: str,
    body: str,
    target: str = "all",
    scholarship_id: int | None = None,
    status_filter: str | None = None,
    student_ids: list[int] | None = None,
) -> int:
    from sqlalchemy import insert as _insert
    from app.models.application import Application as _App, ApplicationStatus as _AS
    if target == "selected" and student_ids:
        ids = student_ids
    elif target == "by_scholarship" and scholarship_id:
        rows = await db.execute(
            select(User.id).join(_App, _App.student_id == User.id).where(
                _App.scholarship_id == scholarship_id, User.role == UserRole.student,
            ).distinct()
        )
        ids = list(rows.scalars().all())
    elif target == "by_status" and status_filter:
        try:
            st = _AS(status_filter)
            rows = await db.execute(
                select(User.id).join(_App, _App.student_id == User.id).where(
                    _App.status == st, User.role == UserRole.student,
                ).distinct()
            )
            ids = list(rows.scalars().all())
        except ValueError:
            ids = []
    else:
        rows = await db.execute(select(User.id).where(User.role == UserRole.student, User.is_active == True))
        ids = list(rows.scalars().all())
    if not ids:
        return 0
    await db.execute(_insert(Notification), [{"user_id": uid, "title": title, "body": body} for uid in ids])
    await db.commit()
    return len(ids)


async def dismiss(db: AsyncSession, user_id: int, notification_id: int) -> None:
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise NotFoundError("Notification", notification_id)
    await db.delete(notif)
    await db.commit()
