"""Settings, tags, accounts and day notes."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from ..config import settings as env_settings
from ..deps import AppConfig, CurrentUser, DbSession
from ..models import Account, DayNote, Tag, Trade, TradeTag
from ..schemas import (
    AccountIn,
    AccountOut,
    DayNoteIn,
    DayNoteOut,
    TagIn,
    TagOut,
)
from ..services.aggregation import recompute_all
from ..services.appsettings import DEFAULT_SETTINGS, get_app_settings, save_app_settings

router = APIRouter(tags=["settings"])


# --- application settings ---------------------------------------------------


@router.get("/settings")
def read_settings(_user: CurrentUser, config: AppConfig) -> dict[str, Any]:
    return config


@router.get("/settings/defaults")
def read_default_settings(_user: CurrentUser) -> dict[str, Any]:
    return DEFAULT_SETTINGS


@router.put("/settings")
async def update_settings(
    request: Request, _user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    patch = await request.json()
    if not isinstance(patch, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Settings payload must be an object")

    before = get_app_settings(db)
    merged = save_app_settings(db, patch)

    # Anything that changes how a trade is scored requires a recompute pass.
    if before["risk"] != merged["risk"] or before["general"]["timezone"] != merged["general"]["timezone"]:
        recompute_all(db, merged["risk"], merged["general"]["timezone"])
    db.commit()
    return merged


@router.post("/settings/recompute")
def recompute(_user: CurrentUser, db: DbSession, config: AppConfig) -> dict[str, int]:
    count = recompute_all(db, config["risk"], config["general"]["timezone"])
    db.commit()
    return {"recomputed": count}


@router.get("/settings/system")
def system_info(_user: CurrentUser, db: DbSession) -> dict[str, Any]:
    return {
        "version": env_settings.version,
        "data_dir": str(env_settings.data_dir),
        "ingest_token_configured": bool(env_settings.ingest_token),
        "secret_key_ephemeral": env_settings.secret_key_is_ephemeral,
        "trades": db.scalar(select(func.count()).select_from(Trade)) or 0,
        "accounts": db.scalar(select(func.count()).select_from(Account)) or 0,
    }


# --- tags -------------------------------------------------------------------


@router.get("/tags", response_model=list[TagOut])
def list_tags(_user: CurrentUser, db: DbSession) -> list[Tag]:
    return list(db.scalars(select(Tag).order_by(Tag.category, Tag.sort_order, Tag.name)).all())


@router.get("/tags/usage")
def tag_usage(_user: CurrentUser, db: DbSession) -> dict[str, int]:
    rows = db.execute(
        select(Tag.name, func.count(TradeTag.trade_id))
        .join(TradeTag, TradeTag.tag_id == Tag.id, isouter=True)
        .group_by(Tag.id)
    ).all()
    return dict(rows)


@router.post("/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
def create_tag(payload: TagIn, _user: CurrentUser, db: DbSession) -> Tag:
    existing = db.scalar(select(Tag).where(func.lower(Tag.name) == payload.name.strip().lower()))
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "A tag with that name already exists")
    tag = Tag(**payload.model_dump())
    tag.name = tag.name.strip()
    db.add(tag)
    db.commit()
    db.refresh(tag)
    return tag


@router.patch("/tags/{tag_id}", response_model=TagOut)
def update_tag(tag_id: int, payload: TagIn, _user: CurrentUser, db: DbSession) -> Tag:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    for key, value in payload.model_dump().items():
        setattr(tag, key, value)
    tag.name = tag.name.strip()
    db.commit()
    db.refresh(tag)
    return tag


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tag(tag_id: int, _user: CurrentUser, db: DbSession) -> None:
    tag = db.get(Tag, tag_id)
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tag not found")
    db.execute(TradeTag.__table__.delete().where(TradeTag.tag_id == tag_id))
    db.delete(tag)
    db.commit()


# --- accounts ---------------------------------------------------------------


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(_user: CurrentUser, db: DbSession) -> list[Account]:
    return list(db.scalars(select(Account).order_by(Account.id)).all())


@router.patch("/accounts/{account_id}", response_model=AccountOut)
def update_account(
    account_id: int, payload: AccountIn, _user: CurrentUser, db: DbSession, config: AppConfig
) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")

    data = payload.model_dump(exclude_unset=True)
    if data.get("is_default"):
        for other in db.scalars(select(Account)).all():
            other.is_default = False
    for key, value in data.items():
        if value is not None:
            setattr(account, key, value)

    if "initial_balance" in data:
        recompute_all(db, config["risk"], config["general"]["timezone"])
    db.commit()
    db.refresh(account)
    return account


# --- day notes --------------------------------------------------------------


@router.get("/notes/{day}", response_model=DayNoteOut | None)
def get_day_note(day: date, _user: CurrentUser, db: DbSession) -> DayNote | None:
    return db.scalar(select(DayNote).where(DayNote.day == day))


@router.put("/notes", response_model=DayNoteOut)
def upsert_day_note(payload: DayNoteIn, _user: CurrentUser, db: DbSession) -> DayNote:
    note = db.scalar(select(DayNote).where(DayNote.day == payload.day))
    if note is None:
        note = DayNote(day=payload.day)
        db.add(note)
    note.content = payload.content
    note.mood = payload.mood
    db.commit()
    db.refresh(note)
    return note


@router.get("/notes", response_model=list[DayNoteOut])
def list_day_notes(_user: CurrentUser, db: DbSession, start: date, end: date) -> list[DayNote]:
    return list(
        db.scalars(
            select(DayNote).where(DayNote.day >= start, DayNote.day <= end).order_by(DayNote.day)
        ).all()
    )
