from fastapi import APIRouter, Depends, Response, Cookie, Request
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user

bearer = HTTPBearer(auto_error=False)
from app.schemas.auth import SignUpRequest, LoginRequest, TokenResponse
from app.schemas.user import UserResponse
from app.services import auth_service
from app.exceptions import ValidationError
from app.config import settings
from app.limiter import limiter


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str

class SupabaseResetPasswordRequest(BaseModel):
    access_token: str
    new_password: str

class ConfirmEmailTokenRequest(BaseModel):
    access_token: str

class ResendVerificationRequest(BaseModel):
    email: str


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/resend-verification", status_code=200)
@limiter.limit("3/minute")
async def resend_verification(request: Request, data: ResendVerificationRequest):
    await auth_service.resend_verification_email(data.email)
    # Always return success to avoid email enumeration
    return {"message": "If that email is registered and unverified, a new link has been sent."}


@router.post("/signup", status_code=200)
@limiter.limit("5/minute")
async def signup(request: Request, data: SignUpRequest, db: AsyncSession = Depends(get_db)):
    result = await auth_service.signup(db, data)
    if result.get("dev"):
        return {"message": "Dev mode: email auto-verified. You can now log in."}
    return {"message": "Verification email sent. Please check your inbox."}


@router.get("/verify-email")
async def verify_email(code: str | None = None, db: AsyncSession = Depends(get_db)):
    if not code:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=invalid_token")

    email = await auth_service.verify_email_and_activate(db, code)
    if not email:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=invalid_token")

    return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?verified=true")


def _set_auth_cookies(response: Response, tokens: dict, remember_me: bool = False) -> str:
    """Set auth cookies and return the CSRF token so it can be included in the response body.

    The csrf_token cookie is scoped to the Railway domain and cannot be read by
    JavaScript running on the Vercel frontend (different domain). Returning it in
    the response body lets the frontend store it in localStorage and send it as
    the X-CSRF-Token header on mutating requests.
    """
    from app.csrf import generate_csrf_token
    csrf = generate_csrf_token()
    max_age_refresh = 60 * 60 * 24 * 30 if remember_me else 60 * 60 * 24 * 7
    max_age_access  = 60 * 16  # 16 min (slightly > 15-min token lifetime)

    response.set_cookie(
        "access_token", tokens["access_token"],
        httponly=True, secure=True, samesite="none", max_age=max_age_access,
    )
    response.set_cookie(
        "refresh_token", tokens["refresh_token"],
        httponly=True, secure=True, samesite="none", max_age=max_age_refresh,
    )
    # Keep the cookie for same-origin / browser-native clients
    response.set_cookie(
        "csrf_token", csrf,
        httponly=False, secure=True, samesite="none", max_age=max_age_access,
    )
    return csrf


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    tokens = await auth_service.login(db, data)
    csrf = _set_auth_cookies(response, tokens, remember_me=data.remember_me)
    return {**TokenResponse(access_token=tokens["access_token"]).model_dump(), "csrf_token": csrf}


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("30/minute")
async def refresh(
    request: Request,  # noqa: ARG001 — consumed by @limiter.limit
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    from app.exceptions import UnauthorizedError
    if not refresh_token:
        raise UnauthorizedError("No refresh token")
    tokens = await auth_service.refresh_tokens(db, refresh_token)
    csrf = _set_auth_cookies(response, tokens)
    return {**TokenResponse(access_token=tokens["access_token"]).model_dump(), "csrf_token": csrf}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
):
    import hashlib
    from app.token_blacklist import revoke_and_persist

    # Revoke whichever token we can find (header OR cookie)
    token = credentials.credentials if credentials else request.cookies.get("access_token")
    if token:
        await revoke_and_persist(hashlib.sha256(token.encode()).hexdigest(), db)

    response.delete_cookie("access_token", samesite="none", secure=True)
    response.delete_cookie("refresh_token", samesite="none", secure=True)
    response.delete_cookie("csrf_token", samesite="none", secure=True)
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def me(current_user=Depends(get_current_user)):
    return current_user


@router.post("/change-password", status_code=200)
async def change_password(
    data: ChangePasswordRequest,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if len(data.new_password) < 8:
        raise ValidationError("New password must be at least 8 characters")
    await auth_service.change_password(db, current_user, data.current_password, data.new_password)
    return {"message": "Password updated successfully"}


@router.post("/forgot-password", status_code=200)
@limiter.limit("5/15minutes")
async def forgot_password(request: Request, data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):  # noqa: ARG001
    await auth_service.send_password_reset(db, data.email)
    return {"message": "If that email is registered, a reset link has been sent."}


@router.get("/reset-callback")
async def reset_callback(code: str | None = None):
    if not code:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=invalid_token")

    token = await auth_service.handle_reset_callback(code)
    if not token:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=invalid_token")

    return RedirectResponse(url=f"{settings.FRONTEND_URL}/reset-password?token={token}")


@router.post("/reset-password", status_code=200)
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    if len(data.new_password) < 8:
        raise ValidationError("Password must be at least 8 characters")
    await auth_service.reset_password(db, data.token, data.new_password)
    return {"message": "Password reset successfully. You can now log in."}


@router.post("/reset-password-token", status_code=200)
async def reset_password_token(data: SupabaseResetPasswordRequest):
    if len(data.new_password) < 8:
        raise ValidationError("Password must be at least 8 characters")
    await auth_service.reset_password_with_supabase_token(data.access_token, data.new_password)
    return {"message": "Password reset successfully. You can now log in."}


@router.post("/confirm-email-token", status_code=200)
async def confirm_email_token(data: ConfirmEmailTokenRequest, db: AsyncSession = Depends(get_db)):
    email = await auth_service.verify_email_with_token(db, data.access_token)
    if not email:
        raise ValidationError("Verification link has expired or is invalid.")
    return {"message": "Email verified. You can now log in."}
