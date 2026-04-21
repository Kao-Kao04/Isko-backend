from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import AuditEntry


async def append_audit(
    db: AsyncSession,
    application_id: int,
    actor_id: int,
    action: str,
    from_status: str | None = None,
    to_status: str | None = None,
    note: str | None = None,
) -> None:
    entry = AuditEntry(
        application_id=application_id,
        actor_id=actor_id,
        action=action,
        from_status=from_status,
        to_status=to_status,
        note=note,
    )
    db.add(entry)
