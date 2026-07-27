"""Accounts and the copier's per-account configuration.

One master account is the source of trades; every other account is a slave
that follows it. The endpoints here are what the Accounts page drives.

Two rules are enforced at this layer rather than left to the UI, because they
protect real money:

* a slave only ever *becomes* live through an explicit arm call, never as a
  side effect of being created or edited, and
* arming is refused unless the account has a trade-enabled password stored,
  since a slave with no password would sit there failing every order.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import get_current_user
from ..models import Account, CopyEvent, CopyLink
from ..schemas import (
    AccountIn,
    AccountOut,
    CopyEventOut,
    CopySettingsOut,
    SlaveAccountIn,
    SlaveAccountOut,
    SlaveArmIn,
)
from ..services.copier.config import defaults as copy_defaults
from ..services.crypto import decrypt, encrypt

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[Depends(get_current_user)])


def _as_out(account: Account, db: Session) -> SlaveAccountOut:
    open_copies = db.scalar(
        select(func.count(CopyLink.id)).where(
            CopyLink.slave_account_id == account.id, CopyLink.status == "open"
        )
    )
    settings = {**copy_defaults(), **(account.copy_settings or {})}
    return SlaveAccountOut(
        id=account.id,
        login=account.login,
        name=account.name,
        broker=account.broker,
        server=account.server,
        currency=account.currency,
        role=account.role,
        balance=account.balance,
        equity=account.equity,
        is_default=account.is_default,
        last_sync_at=account.last_sync_at,
        copy_enabled=account.copy_enabled,
        copy_dry_run=account.copy_dry_run,
        copy_halted=account.copy_halted,
        copy_halt_reason=account.copy_halt_reason,
        copy_halted_at=account.copy_halted_at,
        has_password=bool(decrypt(account.password_enc or "")),
        symbol_prefix=account.symbol_prefix,
        symbol_suffix=account.symbol_suffix,
        symbol_map=account.symbol_map or {},
        settings=CopySettingsOut(**settings),
        open_copies=open_copies or 0,
    )


def _get(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account")
    return account


@router.get("", response_model=list[SlaveAccountOut])
def list_accounts(db: Session = Depends(get_db)) -> list[SlaveAccountOut]:
    accounts = db.scalars(select(Account).order_by(Account.role.desc(), Account.id)).all()
    return [_as_out(account, db) for account in accounts]


@router.post("", response_model=SlaveAccountOut, status_code=status.HTTP_201_CREATED)
def add_slave(payload: SlaveAccountIn, db: Session = Depends(get_db)) -> SlaveAccountOut:
    """Add a slave account. It is created disabled and in dry-run."""
    login = payload.login.strip()
    server = payload.server.strip()

    existing = db.scalar(
        select(Account).where(Account.login == login, Account.server == server)
    )
    if existing is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Account {login} on {server} is already here.",
        )

    account = Account(
        login=login,
        server=server,
        name=payload.name.strip() or f"{login} @ {server}",
        broker=payload.broker.strip(),
        currency=payload.currency.strip() or "USD",
        role="slave",
        password_enc=encrypt(payload.password) if payload.password else "",
        symbol_prefix=payload.symbol_prefix.strip(),
        symbol_suffix=payload.symbol_suffix.strip(),
        symbol_map=payload.symbol_map or {},
        copy_settings={**copy_defaults(), **(payload.settings or {})},
        # Never live on creation, whatever the caller asked for.
        copy_enabled=False,
        copy_dry_run=True,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return _as_out(account, db)


@router.put("/{account_id}", response_model=SlaveAccountOut)
def update_account(
    account_id: int, payload: SlaveAccountIn, db: Session = Depends(get_db)
) -> SlaveAccountOut:
    account = _get(db, account_id)

    account.name = payload.name.strip() or account.name
    account.broker = payload.broker.strip()
    account.currency = payload.currency.strip() or account.currency
    account.symbol_prefix = payload.symbol_prefix.strip()
    account.symbol_suffix = payload.symbol_suffix.strip()
    account.symbol_map = payload.symbol_map or {}

    if account.role == "slave":
        account.login = payload.login.strip() or account.login
        account.server = payload.server.strip() or account.server

    # Omitted password means "leave it"; an empty string means "forget it".
    if payload.password is not None:
        account.password_enc = encrypt(payload.password) if payload.password else ""
        if not payload.password:
            # Without a password it cannot trade, so it must not stay armed.
            account.copy_enabled = False

    if payload.settings is not None:
        account.copy_settings = {**copy_defaults(), **payload.settings}

    db.commit()
    db.refresh(account)
    return _as_out(account, db)


@router.post("/{account_id}/arm", response_model=SlaveAccountOut)
def arm(account_id: int, payload: SlaveArmIn, db: Session = Depends(get_db)) -> SlaveAccountOut:
    """Enable copying, and choose between dry-run and live.

    Going live is the only place in the application where a stored password
    starts being used to place orders, so it is a deliberate call of its own.
    """
    account = _get(db, account_id)
    if account.role != "slave":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only a slave account copies trades.")

    if payload.enabled and not payload.dry_run and not decrypt(account.password_enc or ""):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This account has no trade-enabled password stored, so it cannot place "
            "orders. Add one before taking it live.",
        )

    account.copy_enabled = payload.enabled
    account.copy_dry_run = payload.dry_run
    if payload.enabled:
        # Arming clears a previous halt: the point is to start again.
        account.copy_halted = False
        account.copy_halt_reason = ""
        account.copy_halted_at = None

    db.add(
        CopyEvent(
            slave_account_id=account.id,
            action="resume" if payload.enabled else "halt",
            outcome="ok",
            message=(
                f"copying {'enabled' if payload.enabled else 'disabled'}"
                f"{' (dry run)' if payload.enabled and payload.dry_run else ''}"
            ),
        )
    )
    db.commit()
    db.refresh(account)
    return _as_out(account, db)


@router.post("/{account_id}/resume", response_model=SlaveAccountOut)
def clear_halt(account_id: int, db: Session = Depends(get_db)) -> SlaveAccountOut:
    """Clear a tripped guard so the account can copy again."""
    account = _get(db, account_id)
    account.copy_halted = False
    account.copy_halt_reason = ""
    account.copy_halted_at = None
    db.add(
        CopyEvent(
            slave_account_id=account.id,
            action="resume",
            outcome="ok",
            message="halt cleared by hand",
        )
    )
    db.commit()
    db.refresh(account)
    return _as_out(account, db)


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_account(account_id: int, db: Session = Depends(get_db)) -> None:
    account = _get(db, account_id)
    if account.role == "master":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The master account cannot be removed here; it holds your journal.",
        )
    db.delete(account)
    db.commit()


@router.get("/{account_id}/events", response_model=list[CopyEventOut])
def account_events(
    account_id: int, limit: int = 100, db: Session = Depends(get_db)
) -> list[CopyEvent]:
    _get(db, account_id)
    return list(
        db.scalars(
            select(CopyEvent)
            .where(CopyEvent.slave_account_id == account_id)
            .order_by(CopyEvent.created_at.desc())
            .limit(max(1, min(limit, 500)))
        )
    )


@router.get("/events/recent", response_model=list[CopyEventOut])
def recent_events(limit: int = 100, db: Session = Depends(get_db)) -> list[CopyEvent]:
    """The copier's activity across every account, newest first."""
    return list(
        db.scalars(
            select(CopyEvent).order_by(CopyEvent.created_at.desc()).limit(max(1, min(limit, 500)))
        )
    )


@router.patch("/{account_id}/journal", response_model=AccountOut)
def update_journal_fields(
    account_id: int, payload: AccountIn, db: Session = Depends(get_db)
) -> Account:
    """The journal-side fields, kept separate from the copier's."""
    account = _get(db, account_id)
    if payload.name is not None:
        account.name = payload.name
    if payload.initial_balance is not None:
        account.initial_balance = payload.initial_balance
    if payload.currency is not None:
        account.currency = payload.currency
    if payload.is_default:
        for other in db.scalars(select(Account).where(Account.id != account.id)):
            other.is_default = False
        account.is_default = True
    db.commit()
    db.refresh(account)
    return account


def halt_account(db: Session, account: Account, reason: str, rule: str = "") -> None:
    """Record a tripped guard. Used by the copy loop, exposed here for reuse."""
    account.copy_halted = True
    account.copy_halt_reason = reason[:255]
    account.copy_halted_at = datetime.now(timezone.utc)
    db.add(
        CopyEvent(
            slave_account_id=account.id,
            action="halt",
            outcome="halted",
            rule=rule,
            message=reason,
        )
    )


def settings_payload(account: Account) -> dict[str, Any]:
    return {**copy_defaults(), **(account.copy_settings or {})}
