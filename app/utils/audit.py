from sqlalchemy.ext.asyncio import AsyncSession
from app.models.audit import AuditEntry
from app.models.system_audit import SystemAuditLog


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


async def log_system_audit(
    db: AsyncSession,
    actor_id: int | None,
    entity_type: str,
    action: str,
    entity_id: int | None = None,
    before_state: dict | None = None,
    after_state: dict | None = None,
    ip_address: str | None = None,
) -> None:
    entry = SystemAuditLog(
        actor_id=actor_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        before_state=before_state,
        after_state=after_state,
        ip_address=ip_address,
    )
    db.add(entry)
