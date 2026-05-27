import os
from slowapi import Limiter
from starlette.requests import Request

TRUSTED_PROXY_IPS = set(filter(None, os.getenv("TRUSTED_PROXY_IPS", "").split(",")))


def _get_real_ip(request: Request) -> str:
    if request.client and request.client.host in TRUSTED_PROXY_IPS:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_get_real_ip)
