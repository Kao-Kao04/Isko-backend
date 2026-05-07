from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.limiter import limiter
from app.routers import auth, users, scholarships, applications, documents, notifications, scholars, reports, admin, registration, ws, workflow

app = FastAPI(title="IskoMo API", version="1.0.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    if settings.ENVIRONMENT == "production":
        return JSONResponse(status_code=500, content={"code": "INTERNAL_ERROR", "message": "An unexpected error occurred"})
    raise exc


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
app.include_router(ws.router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/admin/run-migrations")
async def run_migrations(request: Request):
    secret = request.headers.get("x-migration-secret", "")
    if secret != settings.SECRET_KEY:
        from app.exceptions import ForbiddenError
        raise ForbiddenError()
    import subprocess
    result = subprocess.run(
        ["alembic", "upgrade", "heads"],
        capture_output=True, text=True, cwd="/app"
    )
    return {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "returncode": result.returncode,
    }
