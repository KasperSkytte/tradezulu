"""The Expert Advisor's side of the copier.

The MetaTrader Python API cannot be relied on under Wine, so nothing here
depends on it. Instead an Expert Advisor runs *inside* each terminal and talks
to TradeZulu over plain HTTP, which MetaTrader supports natively through
``WebRequest``.

The whole protocol is one call:

    POST /api/agent/poll   {account state, open positions}
                        -> {commands to carry out}

Everything is driven by the terminal reaching out. That matters for more than
tidiness: it means no inbound connection to the terminal, no port to open, and
a terminal behind NAT or on someone's laptop works exactly like one in a
container. Results come back on the following poll, so a lost reply costs one
cycle rather than a duplicate order.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require_ingest_auth
from ..models import Account, CopyEvent
from ..schemas import AgentCommandResult, AgentPollIn, AgentPollOut
from ..services.copier.agent import (
    commands_for,
    record_result,
    update_account_state,
)

log = logging.getLogger(__name__)

router = APIRouter(
    prefix="/agent",
    tags=["agent"],
    dependencies=[Depends(require_ingest_auth)],
)


def _find_account(db: Session, login: str, server: str) -> Account | None:
    """Match the terminal to an account we know about.

    Login alone is not enough: the same number can exist at two brokers, and
    copying to the wrong one would be an expensive mistake.
    """
    login, server = login.strip(), server.strip()
    account = db.scalar(
        select(Account).where(Account.login == login, Account.server == server)
    )
    if account is not None:
        return account
    # A terminal may report a server string that differs in case or spacing.
    for candidate in db.scalars(select(Account).where(Account.login == login)):
        if candidate.server.strip().lower() == server.lower():
            return candidate
    return None


@router.post("/poll", response_model=AgentPollOut)
def poll(payload: AgentPollIn, db: Session = Depends(get_db)) -> AgentPollOut:
    """One heartbeat from a terminal: here is my state, what should I do?"""
    account = _find_account(db, payload.login, payload.server)
    if account is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No account {payload.login!r} on {payload.server!r} is configured in "
            "TradeZulu. Add it under Accounts first.",
        )

    # Results first: a command that has already been carried out must not be
    # handed out again by the planning that follows.
    for result in payload.results:
        record_result(db, account, result)
    # The session runs with autoflush off, so the links just written have to be
    # pushed before the planning below can see them -- otherwise a position the
    # terminal has only this moment confirmed looks like it was never opened.
    db.flush()

    update_account_state(db, account, payload)

    try:
        commands = commands_for(db, account, payload)
    except Exception:  # noqa: BLE001 - a planning fault must not stop the heartbeat
        log.exception("agent: could not plan for account %s", account.id)
        commands = []

    account.last_sync_at = datetime.now(timezone.utc)
    account.last_sync_source = "agent"
    db.commit()

    return AgentPollOut(
        account_id=account.id,
        role=account.role,
        enabled=bool(account.copy_enabled),
        dry_run=bool(account.copy_dry_run),
        halted=bool(account.copy_halted),
        poll_seconds=2 if account.role == "slave" and account.copy_enabled else 10,
        commands=commands,
    )


@router.post("/result", status_code=status.HTTP_204_NO_CONTENT)
def result(payload: AgentCommandResult, db: Session = Depends(get_db)) -> None:
    """Report a command's outcome out of band, for a terminal that prefers to."""
    account = db.get(Account, payload.account_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such account")
    record_result(db, account, payload)
    db.commit()


@router.get("/hello")
def hello(db: Session = Depends(get_db)) -> dict[str, Any]:
    """A cheap check the EA can call to prove its URL and token are right."""
    return {
        "ok": True,
        "accounts": [
            {"login": a.login, "server": a.server, "role": a.role}
            for a in db.scalars(select(Account))
        ],
    }


def log_event(db: Session, account: Account, action: str, outcome: str, message: str) -> None:
    db.add(
        CopyEvent(
            slave_account_id=account.id,
            action=action,
            outcome=outcome,
            message=message[:2000],
        )
    )
