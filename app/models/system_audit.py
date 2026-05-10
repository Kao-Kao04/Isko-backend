from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class SystemAuditLog(Base):
    """Audit trail for admin/system-level actions not tied to a specific application."""
    __tablename__ = "system_audit_logs"

    id          = Column(Integer, primary_key=True, index=True)
    actor_id    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    entity_type = Column(String(64), nullable=False)   # "user" | "scholarship" | "scholar" | "broadcast"
    entity_id   = Column(Integer, nullable=True)
    action      = Column(String(128), nullable=False)
    before_state = Column(JSON, nullable=True)
    after_state  = Column(JSON, nullable=True)
    ip_address  = Column(String(64), nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    actor = relationship("User", foreign_keys=[actor_id])
