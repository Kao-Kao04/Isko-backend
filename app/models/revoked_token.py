from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.sql import func
from app.database import Base


class RevokedToken(Base):
    """Persists token revocations across server restarts.

    The in-memory TTLCache in token_blacklist.py is the hot path.
    This table is the source of truth loaded on startup and written on logout.
    """
    __tablename__ = "revoked_tokens"

    id         = Column(Integer, primary_key=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
