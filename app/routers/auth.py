from fastapi import APIRouter, Depends, Response, Cookie
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.database import get_db
from app.dependencies import get_current_user
from app.schemas.auth import SignUpRequest, LoginRequest, TokenResponse
from app.schemas.user import UserResponse
from app.services import auth_service
from app.utils.security import verify_password, hash_password
from app.exceptions import ValidationError
from app.config import settings


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/signup", status_code=200)
async def signup(data: SignUpRequest, db: AsyncSession = Depends(get_db)):
    result = await auth_service.signup(db, data)
    if result.get("dev"):
        return {"message": "Dev mode: email auto-verified. You can now log in."}
    return {"message": "Verification email sent. Please check your inbox."}


@router.get("/verify-email")
async def verify_email(token: str | None = None, db: AsyncSession = Depends(get_db)):
    if not token:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=invalid_token")

    email = await auth_service.verify_email_and_activate(db, token)
    if not email:
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=invalid_token")

    return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?verified=true")


@router.post("/login")
async def login(data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    tokens = await auth_service.login(db, data)
    response.set_cookie(
        "refresh_token", tokens["refresh_token"],
        httponly=True, secure=True, samesite="none", max_age=60 * 60 * 24 * 7,
    )
    return TokenResponse(access_token=tokens["access_token"])


@router.post("/refresh", response_model=TokenResponse)
async def refresh(response: Response, refresh_token: str | None = Cookie(default=None)):
    from app.exceptions import UnauthorizedError
    if not refresh_token:
        raise UnauthorizedError("No refresh token")
    tokens = auth_service.refresh_tokens(refresh_token)
    response.set_cookie(
        "refresh_token", tokens["refresh_token"],
        httponly=True, secure=True, samesite="none", max_age=60 * 60 * 24 * 7,
    )
    return TokenResponse(access_token=tokens["access_token"])


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("refresh_token")
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
    if not verify_password(data.current_password, current_user.hashed_password):
        raise ValidationError("Current password is incorrect")
    if len(data.new_password) < 8:
        raise ValidationError("New password must be at least 8 characters")
    current_user.hashed_password = hash_password(data.new_password)
    await db.commit()
    return {"message": "Password updated successfully"}


@router.post("/forgot-password", status_code=200)
async def forgot_password(data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    # Always return 200 to prevent email enumeration
    await auth_service.send_password_reset(db, data.email)
    return {"message": "If that email is registered, a reset link has been sent."}


@router.post("/reset-password", status_code=200)
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    if len(data.new_password) < 8:
        raise ValidationError("Password must be at least 8 characters")
    await auth_service.reset_password(db, data.token, data.new_password)
    return {"message": "Password reset successfully. You can now log in."}
