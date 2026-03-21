from __future__ import annotations

from typing import Any, Literal

from aegra_api.models.auth import User
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.auth.core import (
    authenticate_user,
    create_access_token,
    get_access_token_ttl_seconds,
    register_user,
)
from app.core.auth import authenticated_user

router = APIRouter(prefix="/auth", tags=["auth"])
ACCESS_TOKEN_COOKIE_NAME = "aegra_access_token"  # nosec B105


def _access_token_cookie_max_age_seconds() -> int:
    return get_access_token_ttl_seconds()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: Literal["admin", "premium", "developer", "reviewer", "free"] | None = None
    team_id: str | None = Field(default=None, max_length=64)


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: dict[str, Any]


@router.post("/register", response_model=LoginResponse)
async def register(payload: RegisterRequest, response: Response) -> LoginResponse:
    try:
        user = await register_user(
            username=payload.username,
            password=payload.password,
            role=payload.role,
            team_id=payload.team_id,
        )
    except ValueError as exc:
        detail = str(exc)
        if "已存在" in detail:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=detail,
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=detail
        ) from exc

    token = create_access_token(user)
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
        max_age=_access_token_cookie_max_age_seconds(),
    )
    return LoginResponse(access_token=token, user=user)


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, response: Response) -> LoginResponse:
    try:
        user = await authenticate_user(
            username=payload.username,
            password=payload.password,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    token = create_access_token(user)
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
        max_age=_access_token_cookie_max_age_seconds(),
    )
    return LoginResponse(access_token=token, user=user)


@router.get("/me")
async def me(user: User = Depends(authenticated_user)) -> dict[str, Any]:
    return {
        "identity": user.identity,
        "display_name": user.display_name,
        "is_authenticated": user.is_authenticated,
        "permissions": user.permissions,
        "role": getattr(user, "role", None),
        "subscription_tier": getattr(user, "subscription_tier", None),
        "team_id": getattr(user, "team_id", None),
        "email": getattr(user, "email", None),
    }


@router.post("/logout")
async def logout(
    response: Response, _user: User = Depends(authenticated_user)
) -> dict[str, bool]:
    response.delete_cookie(ACCESS_TOKEN_COOKIE_NAME, path="/")
    return {"ok": True}
