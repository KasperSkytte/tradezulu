"""Login, logout and password management for the single journal user."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import select

from ..config import settings
from ..deps import CurrentUser, DbSession
from ..models import User
from ..schemas import LoginRequest, PasswordChange, UserOut
from ..security import (
    create_session_token,
    hash_password,
    login_throttle,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_key(request: Request) -> str:
    # Behind nginx the real address arrives in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _set_cookie(response: Response, token: str, remember: bool) -> None:
    response.set_cookie(
        key=settings.cookie_name,
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_days * 86400 if remember else None,
        path="/",
    )


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, request: Request, response: Response, db: DbSession) -> User:
    key = _client_key(request)
    wait = login_throttle.retry_after(key)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Too many failed attempts. Try again in {wait} seconds.",
            headers={"Retry-After": str(wait)},
        )

    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not verify_password(payload.password, user.password_hash):
        login_throttle.record_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    login_throttle.reset(key)
    user.last_login_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()

    token = create_session_token(user.id, user.username, user.token_version)
    _set_cookie(response, token, payload.remember)
    return user


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(settings.cookie_name, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.post("/password")
def change_password(
    payload: PasswordChange, user: CurrentUser, response: Response, db: DbSession
) -> dict[str, bool]:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    try:
        user.password_hash = hash_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    # Invalidate every other session, then re-issue one for this browser.
    user.token_version += 1
    db.commit()
    _set_cookie(response, create_session_token(user.id, user.username, user.token_version), True)
    return {"ok": True}
