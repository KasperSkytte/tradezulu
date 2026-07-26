"""Shared FastAPI dependencies."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import Account, User
from .security import constant_time_equals, decode_session_token
from .services.appsettings import get_app_settings

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, db: DbSession) -> User:
    token = request.cookies.get(settings.cookie_name)
    if not token:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")

    payload = decode_session_token(token)
    if not payload:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired")

    user = db.get(User, int(payload.get("sub", 0)))
    if user is None or user.token_version != payload.get("ver"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session is no longer valid")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_ingest_auth(
    request: Request,
    db: DbSession,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    """MT5 clients authenticate with a shared token, browsers with a cookie."""
    if settings.ingest_token:
        if x_api_key and constant_time_equals(x_api_key, settings.ingest_token):
            return
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer ") and constant_time_equals(
            auth[7:].strip(), settings.ingest_token
        ):
            return
    try:
        get_current_user(request, db)
        return
    except HTTPException:
        pass
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing ingest credentials")


def get_app_config(db: DbSession) -> dict[str, Any]:
    return get_app_settings(db)


AppConfig = Annotated[dict[str, Any], Depends(get_app_config)]


def get_default_account(db: Session) -> Account | None:
    account = db.scalar(select(Account).where(Account.is_default.is_(True)).limit(1))
    if account is None:
        account = db.scalar(select(Account).order_by(Account.id).limit(1))
    return account


class DateRange:
    def __init__(self, start: date, end: date) -> None:
        self.start = start
        self.end = end


def date_range(
    config: AppConfig,
    start: Annotated[date | None, Query(description="Inclusive start date")] = None,
    end: Annotated[date | None, Query(description="Inclusive end date")] = None,
    period: Annotated[str | None, Query(description="Preset period id")] = None,
) -> DateRange:
    from .services.metrics import period_bounds

    today = date.today()
    if start and end:
        return DateRange(start, end)
    preset = period or config["general"].get("default_period", "last_30_days")
    bounds = period_bounds(preset, today, config["general"].get("week_starts_on", "monday"))
    return DateRange(start or bounds[0], end or bounds[1])


DateRangeDep = Annotated[DateRange, Depends(date_range)]
