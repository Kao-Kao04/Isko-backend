"""
Token blacklist — two-layer design:
  1. In-memory TTLCache (hot path, O(1) lookup on every request)
  2. DB-backed RevokedToken table (survives server restarts)

On startup: unexpired DB rows are loaded into the cache.
On logout:  token is written to both cache and DB.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from cachetools import TTLCache

logger = logging.getLogger(__name__)

_ACCESS_TOKEN_MINUTES = 15
_BLACKLIST_TTL_SECONDS = (_ACCESS_TOKEN_MINUTES + 1) * 60

_blacklist: TTLCache = TTLCache(maxsize=50_000, ttl=_BLACKLIST_TTL_SECONDS)


def revoke(token_hash: str) -> None:
    _blacklist[token_hash] = True


def is_revoked(token_hash: str) -> bool:
    return token_hash in _blacklist


async def revoke_and_persist(token_hash: str, db) -> None:
    """Revoke in memory AND write to DB for restart persistence."""
    revoke(token_hash)
    from app.models.revoked_token import RevokedToken
    from sqlalchemy import select
    existing = await db.execute(select(RevokedToken).where(RevokedToken.token_hash == token_hash))
    if not existing.scalar_one_or_none():
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=_BLACKLIST_TTL_SECONDS)
        db.add(RevokedToken(token_hash=token_hash, expires_at=expires_at))
        await db.commit()


async def load_from_db(db) -> None:
    """Called once on startup — warm the cache from unexpired DB rows."""
    from app.models.revoked_token import RevokedToken
    from sqlalchemy import select, delete
    now = datetime.now(timezone.utc)

    # Purge expired rows first
    await db.execute(delete(RevokedToken).where(RevokedToken.expires_at <= now))
    await db.commit()

    result = await db.execute(select(RevokedToken).where(RevokedToken.expires_at > now))
    loaded = 0
    for row in result.scalars().all():
        _blacklist[row.token_hash] = True
        loaded += 1
    if loaded:
        logger.info("Token blacklist: loaded %d revoked tokens from DB", loaded)
