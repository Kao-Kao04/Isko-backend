from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.config import settings
from app.routers import auth, users, scholarships, applications, documents, notifications, scholars, reports, admin

app = FastAPI(title="IskoMo API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if settings.ENVIRONMENT == "production":
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])


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
app.include_router(scholarships.router)
app.include_router(applications.router)
app.include_router(documents.router)
app.include_router(notifications.router)
app.include_router(scholars.router)
app.include_router(reports.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
