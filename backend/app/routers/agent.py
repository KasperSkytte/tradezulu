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
from ..config import settings
from ..models import Account, CopyEvent
from ..services.credentials import credentials_status, get_credentials
from ..services.crypto import decrypt
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


def _adopt_master(db: Session, login: str, server: str) -> Account | None:
    """Claim the master row for a terminal that proves it is the master.

    Nobody should have to type an account number twice. The user enters their
    credentials once, a terminal comes up on them, and the account identity
    that terminal reports is by definition the right one -- it came from the
    broker, not from a form.

    The proof required is that the terminal is logged into exactly the account
    whose credentials are configured. A terminal reporting anything else gets
    no account, because silently adopting whoever calls would let a stray
    terminal capture the master role and, with it, the trades everything else
    is copied from.
    """
    stored = credentials_status(db)
    want_login = str(stored.get("login") or "").strip()
    want_server = str(stored.get("server") or "").strip()
    if not want_login or not want_server:
        return None
    if login.strip() != want_login or server.strip().lower() != want_server.lower():
        return None

    master = db.scalar(select(Account).where(Account.role == "master"))
    if master is None:
        master = Account(login=login, server=server, name=f"{login} ({server})", role="master")
        db.add(master)
    else:
        master.login, master.server = login, server
    db.flush()
    log.info("agent: master account is now %s on %s", login, server)
    return master


@router.post("/poll", response_model=AgentPollOut)
def poll(payload: AgentPollIn, db: Session = Depends(get_db)) -> AgentPollOut:
    """One heartbeat from a terminal: here is my state, what should I do?"""
    account = _find_account(db, payload.login, payload.server) or _adopt_master(
        db, payload.login, payload.server
    )
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


@router.get("/terminals")
def terminals(db: Session = Depends(get_db)) -> dict[str, Any]:
    """What terminals should be running, for whoever provisions them.

    The provisioner runs beside MetaTrader rather than inside this container,
    because Wine will host a terminal reliably and a container has not. That
    split is an implementation detail the user should never meet, so this
    endpoint hands over everything a terminal needs -- which account, which
    broker, and the URL and token its Expert Advisor should report back on.
    The person adding an account types their broker credentials once, in the
    web interface, and nothing else anywhere.

    The callback URL is deliberately this server's *internal* address. The
    terminal runs on the same machine, so putting a domain in front of
    TradeZulu later changes how people reach the site and nothing about how
    its terminals reach it.
    """
    stored = get_credentials(db)
    wanted: list[dict[str, Any]] = []

    for account in db.scalars(select(Account).order_by(Account.id)):
        if account.role == "master":
            login = str(stored.get("login") or account.login or "").strip()
            server = str(stored.get("server") or account.server or "").strip()
            password = str(stored.get("password") or "")
        else:
            login, server = account.login.strip(), account.server.strip()
            password = decrypt(account.password_enc or "")

        # A terminal with no password cannot log in, and a half-provisioned
        # one that sits at a login prompt is worse than none at all: it looks
        # like it is working. Leave it out until the credentials are there.
        if not (login and server and password):
            continue

        wanted.append(
            {
                "account_id": account.id,
                "role": account.role,
                "login": login,
                "server": server,
                "broker": account.broker or "",
                "password": password,
                "enabled": bool(account.copy_enabled) or account.role == "master",
            }
        )

    return {
        "callback_url": settings.internal_url.rstrip("/") + "/api",
        "api_key": settings.ingest_token or "",
        "terminals": wanted,
    }


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
