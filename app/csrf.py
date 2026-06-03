"""
CSRF protection using the Double Submit Cookie pattern.

On login/refresh, the backend sets two cookies:
  - access_token  (HttpOnly, Secure) — not readable by JS
  - csrf_token    (non-HttpOnly, Secure) — readable by JS

The frontend reads csrf_token from document.cookie and sends it
as the X-CSRF-Token header on every state-changing request.

The middleware validates that header == cookie value.
Skipped for GET/HEAD/OPTIONS and auth endpoints (login/signup/refresh)
that are the entry points for unauthenticated users.
"""
import hmac
import secrets
from fastapi import Request
from fastapi.responses import JSONResponse

CSRF_EXEMPT = {
    "/api/auth/login", "/api/auth/signup", "/api/auth/refresh",
    "/api/auth/logout", "/api/auth/verify-email", "/api/auth/verify-email",
    "/api/auth/forgot-password", "/api/auth/reset-callback",
    "/api/auth/reset-password", "/api/auth/reset-password-token",
    "/api/auth/confirm-email-token", "/health",
    "/api/auth/resend-verification",  # public — no session yet
    "/api/contact",                   # public form — no session to protect
    "/api/admin/test-email",          # diagnostic endpoint
}

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def generate_csrf_token() -> str:
    return secrets.token_hex(32)


async def csrf_middleware(request: Request, call_next):
    if request.method in SAFE_METHODS or request.url.path in CSRF_EXEMPT:
        return await call_next(request)

    # Requests with an explicit Authorization: Bearer header are safe from CSRF —
    # cross-site attackers cannot set custom headers, so the JWT itself is sufficient.
    if request.headers.get("Authorization", "").startswith("Bearer "):
        return await call_next(request)

    # Cookie-only sessions (legacy fallback): enforce double-submit cookie pattern
    cookie_token = request.cookies.get("csrf_token")
    header_token = request.headers.get("X-CSRF-Token")

    if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
        return JSONResponse(
            status_code=403,
            content={"code": "CSRF_INVALID", "message": "Invalid or missing CSRF token"},
        )

    return await call_next(request)
