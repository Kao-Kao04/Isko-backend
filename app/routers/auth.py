from fastapi import APIRouter, Depends, Response, Cookie
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from jose import JWTError

from app.database import get_db
from app.dependencies import get_current_user
from app.schemas.auth import InitiateRegisterRequest, RegisterRequest, LoginRequest, TokenResponse
from app.schemas.user import UserResponse
from app.services import auth_service
from app.utils.security import decode_email_verification_token, create_registration_token
from app.config import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/initiate-register", status_code=200)
async def initiate_register(data: InitiateRegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await auth_service.initiate_register(db, data)
    if result.get("dev"):
        return {"message": "Dev mode: skipping email", "token": result["token"]}
    return {"message": "Verification email sent. Please check your inbox."}


@router.get("/verify-email")
async def verify_email(token: str):
    try:
        payload = decode_email_verification_token(token)
    except (JWTError, ValueError):
        return RedirectResponse(url=f"{settings.FRONTEND_URL}/login?error=invalid_token")
    reg_token = create_registration_token(payload["email"], payload["hashed_password"])
    return RedirectResponse(url=f"{settings.FRONTEND_URL}/register?token={reg_token}")


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.register_student(db, data)


@router.post("/login")
async def login(data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    tokens = await auth_service.login(db, data)
    response.set_cookie(
        "refresh_token", tokens["refresh_token"],
        httponly=True, secure=False, samesite="lax", max_age=60 * 60 * 24 * 7,
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
        httponly=True, secure=False, samesite="lax", max_age=60 * 60 * 24 * 7,
    )
    return TokenResponse(access_token=tokens["access_token"])


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("refresh_token")
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def me(current_user=Depends(get_current_user)):
    return current_user
