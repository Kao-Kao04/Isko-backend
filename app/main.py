import logging
import logging.config

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.limiter import limiter
from app.csrf import csrf_middleware
from app.routers import auth, users, scholarships, applications, documents, notifications, scholars, reports, admin, registration, ws, workflow, compliance

# ── Structured logging ───────────────────────────────────────────────────────
LOG_LEVEL = "INFO" if settings.ENVIRONMENT == "production" else "DEBUG"
logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": '{"time":"%(asctime)s","level":"%(levelname)s","name":"%(name)s","message":"%(message)s"}',
        },
        "dev": {
            "format": "%(levelname)s %(name)s: %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if settings.ENVIRONMENT == "production" else "dev",
        },
    },
    "root": {"level": LOG_LEVEL, "handlers": ["console"]},
    "loggers": {
        "uvicorn.access": {"level": "WARNING"},
        "sqlalchemy.engine": {"level": "WARNING"},
    },
})

logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
_is_prod     = settings.ENVIRONMENT == "production"
_docs_url    = None if _is_prod else "/docs"
_redoc_url   = None if _is_prod else "/redoc"
_openapi_url = None if _is_prod else "/openapi.json"

app = FastAPI(
    title="IskoMo API",
    version="1.0.0",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)


@app.on_event("startup")
async def _warm_token_blacklist() -> None:
    from app.database import AsyncSessionLocal
    from app.token_blacklist import load_from_db
    try:
        async with AsyncSessionLocal() as db:
            await load_from_db(db)
    except Exception as exc:
        logger.warning("Could not load revoked tokens on startup: %s", exc)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Middleware stack — ORDER MATTERS ─────────────────────────────────────────
# FastAPI/Starlette uses LIFO: the LAST middleware registered is OUTERMOST.
# CORSMiddleware must be outermost so it adds Access-Control headers to ALL
# responses including CSRF 403s — otherwise the browser blocks the response
# and the frontend sees "Failed to fetch" instead of the actual error.

app.middleware("http")(csrf_middleware)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://*.supabase.co; "
        "frame-ancestors 'none';"
    )
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


# CORSMiddleware added LAST → outermost → wraps ALL responses including CSRF 403
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-CSRF-Token"],
)


# ── Exception handlers ────────────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"code": "VALIDATION_ERROR", "message": "Request validation failed", "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    from app.exceptions import AppException
    if isinstance(exc, AppException):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    if settings.ENVIRONMENT == "production":
        return JSONResponse(status_code=500, content={"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"})
    raise exc


# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(registration.router)
app.include_router(scholarships.router)
app.include_router(applications.router)
app.include_router(documents.router)
app.include_router(notifications.router)
app.include_router(scholars.router)
app.include_router(reports.router)
app.include_router(admin.router)
app.include_router(workflow.router)
app.include_router(compliance.router)
app.include_router(ws.router)


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    from sqlalchemy import text
    from app.database import AsyncSessionLocal
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        logger.error("Health check failed: %s", exc)
        detail = str(exc) if settings.ENVIRONMENT != "production" else "Database unavailable"
        return JSONResponse(status_code=503, content={"status": "degraded", "detail": detail})
