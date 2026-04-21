from fastapi import APIRouter, Depends, Response, Cookie
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse, RefreshRequest
from app.schemas.user import UserResponse
from app.services import auth_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    return await auth_service.register_student(db, data)


@router.post("/login")
async def login(data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    tokens = await auth_service.login(db, data)
    response.set_cookie(
        "refresh_token", tokens["refresh_token"],
        httponly=True, secure=True, samesite="lax", max_age=60 * 60 * 24 * 7,
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
        httponly=True, secure=True, samesite="lax", max_age=60 * 60 * 24 * 7,
    )
    return TokenResponse(access_token=tokens["access_token"])


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("refresh_token")
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def me(current_user=Depends(get_current_user)):
    return current_user
