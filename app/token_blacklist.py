"""
In-memory token blacklist using TTLCache.
Entries auto-expire after ACCESS_TOKEN_EXPIRE_MINUTES.
Not shared across multiple workers — sufficient for current single-instance deployment.
"""
from cachetools import TTLCache

_BLACKLIST_TTL_SECONDS = 16 * 60  # 16 min — slightly longer than the 15-min token lifetime

_blacklist: TTLCache = TTLCache(maxsize=50_000, ttl=_BLACKLIST_TTL_SECONDS)


def revoke(token_hash: str) -> None:
    _blacklist[token_hash] = True


def is_revoked(token_hash: str) -> bool:
    return token_hash in _blacklist
