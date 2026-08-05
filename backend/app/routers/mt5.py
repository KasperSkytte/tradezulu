"""MetaTrader 5 synchronisation.

Everything arrives by being pushed. An Expert Advisor inside a terminal POSTs
deals here with an API key; this server never reaches out to MetaTrader.

That is not a preference so much as what works. Reaching a terminal from
outside means driving MetaTrader's own inter-process interface, and under Wine
it accepts a connection and then never answers -- see docs/metatrader.md for
what was tried. A terminal talking outwards over plain HTTP has none of that
problem, and it also means no inbound port, so a terminal behind NAT or on
someone's laptop works exactly like one beside this server.

Account credentials are still stored, encrypted: the provisioner needs them to
start a terminal and log it in. They are never used from here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from ..deps import AppConfig, CurrentUser, DbSession, get_default_account, require_ingest_auth
from ..models import Account, Candle, Deal, SyncLog, Trade
from ..schemas import (
    CandleResponse,
    MT5CredentialsIn,
    MT5CredentialsOut,
    MT5IngestRequest,
    MT5IngestResponse,
    SyncStatus,
)
from ..services import brokerclock
from ..services import candles as timeframes
from ..services.accounts import purge_account
from ..services.aggregation import (
    _parse_time,
    rebuild_trades,
    upsert_deals,
)
from ..services.brokers import list_brokers
from ..services.credentials import (
    clear_credentials,
    credentials_status,
    save_credentials,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/mt5", tags=["mt5"])


def _resolve_account(db: Session, info: dict[str, Any]) -> Account:
    """Find or create the account the incoming deals belong to."""
    login = str(info.get("login") or "0")
    server = str(info.get("server") or "")

    account = db.scalar(
        select(Account).where(Account.login == login, Account.server == server)
    )
    if account is None and login != "0":
        # Adopt the placeholder account created on first boot.
        placeholder = db.scalar(select(Account).where(Account.login == "0"))
        if placeholder is not None:
            account = placeholder
            account.login = login
            account.server = server

    if account is None:
        # Not a master. The role column defaults to "master", so every account
        # that arrived this way -- a terminal reporting a login nobody had
        # configured -- became a second one, and a second master is not a
        # thing: "Forget" removes whichever the query happens to return, and
        # the other cannot be removed at all. Promotion is _adopt_master's job
        # and happens only for the account whose credentials are stored.
        account = Account(login=login, server=server, is_default=False, role="slave")
        db.add(account)
        db.flush()
        if db.scalar(select(func.count()).select_from(Account)) == 1:
            account.is_default = True

    account.name = account.name or str(info.get("name") or "")
    account.broker = str(info.get("company") or account.broker)
    account.currency = str(info.get("currency") or account.currency or "USD")
    account.leverage = int(info.get("leverage") or account.leverage or 0)
    if info.get("balance") is not None:
        account.balance = float(info["balance"])
    if info.get("equity") is not None:
        account.equity = float(info["equity"])
    offset = brokerclock.offset_minutes(info.get("server_time"))
    if offset is not None:
        account.broker_utc_offset_minutes = offset
    return account


def _store_candles(db: Session, batches: list[Any]) -> int:
    stored = 0
    for batch in batches:
        symbol = batch.symbol if hasattr(batch, "symbol") else batch["symbol"]
        timeframe = (batch.timeframe if hasattr(batch, "timeframe") else batch["timeframe"]) or "M15"
        candles = batch.candles if hasattr(batch, "candles") else batch["candles"]
        if not candles:
            continue

        times = []
        normalised = []
        for candle in candles:
            data = candle if isinstance(candle, dict) else candle.model_dump()
            when = _parse_time(data["time"])
            when = when.astimezone(timezone.utc).replace(tzinfo=None) if when.tzinfo else when
            times.append(when)
            normalised.append((when, data))

        existing = set(
            db.scalars(
                select(Candle.time).where(
                    Candle.symbol == symbol,
                    Candle.timeframe == timeframe,
                    Candle.time.in_(times),
                )
            ).all()
        )
        for when, data in normalised:
            if when in existing:
                continue
            existing.add(when)
            db.add(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    time=when,
                    open=float(data["open"]),
                    high=float(data["high"]),
                    low=float(data["low"]),
                    close=float(data["close"]),
                    volume=float(data.get("volume") or 0),
                )
            )
            stored += 1
    return stored


def _apply_ingest(
    db: Session,
    config: dict[str, Any],
    account_info: dict[str, Any],
    deals: list[dict[str, Any]],
    candle_batches: list[Any],
    source: str,
) -> MT5IngestResponse:
    account = _resolve_account(db, account_info)
    received, new = upsert_deals(db, account.id, deals)

    touched = {int(d.get("position_id") or 0) for d in deals if d.get("position_id")}
    if new:
        trades = rebuild_trades(
            db,
            account.id,
            config["risk"],
            config["general"]["timezone"],
            position_ids=sorted(touched) or None,
        )
    else:
        trades = 0

    candles = _store_candles(db, candle_batches) if candle_batches else 0

    account.last_sync_at = datetime.now(timezone.utc).replace(tzinfo=None)
    account.last_sync_source = source
    if account.initial_balance <= 0:
        account.initial_balance = _infer_initial_balance(db, account)

    db.add(
        SyncLog(
            account_id=account.id,
            source=source,
            status="ok",
            deals_received=received,
            deals_new=new,
            trades_upserted=trades,
        )
    )
    db.commit()

    last_ticket = (
        db.scalar(select(func.max(Deal.ticket)).where(Deal.account_id == account.id)) or 0
    )
    return MT5IngestResponse(
        account_id=account.id,
        deals_received=received,
        deals_new=new,
        trades_upserted=trades,
        candles_stored=candles,
        last_deal_ticket=last_ticket,
        message=f"{new} new deal(s), {trades} trade(s) updated",
    )


def _infer_initial_balance(db: Session, account: Account) -> float:
    """Deposits and withdrawals arrive as balance-type deals (DEAL_TYPE_BALANCE)."""
    total = db.scalar(
        select(func.sum(Deal.profit)).where(Deal.account_id == account.id, Deal.deal_type == 2)
    )
    if total and total > 0:
        return float(total)
    return account.balance or 0.0


@router.post(
    "/ingest",
    response_model=MT5IngestResponse,
    dependencies=[Depends(require_ingest_auth)],
)
def ingest(payload: MT5IngestRequest, db: DbSession, config: AppConfig) -> MT5IngestResponse:
    """Receive deals pushed by a terminal's Expert Advisor."""
    return _apply_ingest(
        db,
        config,
        payload.account.model_dump(),
        [d.model_dump() for d in payload.deals],
        payload.candles,
        source="ea",
    )


@router.get("/cursor", dependencies=[Depends(require_ingest_auth)])
def cursor(db: DbSession, login: Annotated[str | None, Query()] = None) -> dict[str, Any]:
    """Tell the EA where to resume from, so it only sends what we lack."""
    account = (
        db.scalar(select(Account).where(Account.login == str(login))) if login else get_default_account(db)
    )
    if account is None:
        return {"account_id": None, "last_deal_ticket": 0, "last_deal_time": None}
    last_ticket = db.scalar(select(func.max(Deal.ticket)).where(Deal.account_id == account.id)) or 0
    last_time = db.scalar(select(func.max(Deal.time)).where(Deal.account_id == account.id))
    return {
        "account_id": account.id,
        "last_deal_ticket": int(last_ticket),
        "last_deal_time": last_time.replace(tzinfo=timezone.utc).isoformat() if last_time else None,
    }


@router.get("/brokers")
def brokers(_user: CurrentUser) -> dict[str, Any]:
    """Brokers and their trade servers, for the account form.

    Which MetaTrader build each one needs is not included. That is the
    provisioner's business, and having to know it is the setup step this
    exists to remove.
    """
    return {"brokers": list_brokers()}


@router.get("/credentials", response_model=MT5CredentialsOut)
def read_credentials(_user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """Everything about the stored account except the password itself."""
    return credentials_status(db)


@router.put("/credentials", response_model=MT5CredentialsOut)
def write_credentials(
    payload: MT5CredentialsIn, _user: CurrentUser, db: DbSession
) -> dict[str, Any]:
    # A different account number needs its own password. The form leaves the
    # field blank to mean "keep the stored one", which is right when correcting
    # a server or a typo and wrong the moment the account changes -- the
    # terminal would then start, be refused by the broker on a display nobody
    # is watching, and never report in. Said here rather than discovered there.
    previous = str(credentials_status(db).get("login") or "").strip()
    if previous and previous != payload.login.strip() and not payload.password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Account {payload.login.strip()} is not the one stored ({previous}), so "
            "its password is needed too. Type it in, or use Forget to start fresh.",
        )

    save_credentials(db, payload.server, payload.login, payload.password)
    db.commit()
    return credentials_status(db)


@router.delete("/credentials", response_model=MT5CredentialsOut)
def delete_credentials(_user: CurrentUser, db: DbSession) -> dict[str, Any]:
    """Forget the stored account, and everything it put in the journal.

    Forgetting has to mean forgetting. Clearing the credentials alone left the
    account's trades, deals and equity samples in the database: gone from the
    interface, still counted in every total, and silently inherited by the next
    account added with the same number.

    The terminal that was provisioned from these keeps running until the
    provisioner's next pass, which stops asking for it once it is no longer in
    the plan. Nothing is torn down from here.
    """
    master = db.scalar(select(Account).where(Account.role == "master"))
    if master is not None:
        removed = purge_account(db, master)
        log.info("mt5: forgot account %s and %s trades", master.login, removed["trades"])
    clear_credentials(db)
    db.commit()
    return credentials_status(db)


@router.get("/status", response_model=SyncStatus)
def status_(_user: CurrentUser, db: DbSession, config: AppConfig) -> SyncStatus:
    account = get_default_account(db)
    mode = config["mt5"].get("sync_mode", "ea")

    creds = credentials_status(db)
    message = ""

    # Terminals report in rather than being polled, so "connected" is simply
    # whether one has been heard from lately. A minute is generous: a master
    # polls every ten seconds and a slave every two.
    #
    # The distinction that matters to someone who has just saved an account is
    # between "nothing is happening" and "your terminal is being built". The
    # second takes minutes the first time -- a MetaTrader install has to be
    # copied and logged in -- and without saying so the page looks broken.
    connected: bool | None = None
    phase = "off"
    if mode == "ea":
        if not creds["configured"]:
            phase = "no-account"
            message = "Add your account below and a terminal is started for it."
        elif account is None or account.last_sync_at is None:
            phase = "starting"
            connected = False
            message = (
                "Starting a MetaTrader terminal for this account. The first one "
                "takes a few minutes; after that it is seconds."
            )
        else:
            age = datetime.now(timezone.utc) - account.last_sync_at.replace(tzinfo=timezone.utc)
            connected = age < timedelta(minutes=1)
            phase = "connected" if connected else "stalled"
            if not connected:
                message = (
                    "The terminal has not reported in for "
                    f"{int(age.total_seconds() // 60)} minutes."
                )

    if account is None:
        return SyncStatus(
            account_id=None, login=None, name=None, balance=None, equity=None, currency=None,
            last_sync_at=None, last_sync_source=None, total_deals=0, total_trades=0,
            open_trades=0, sync_mode=mode, connected=connected, phase=phase,
            credentials_configured=creds["configured"], message=message,
        )

    return SyncStatus(
        account_id=account.id,
        login=account.login,
        name=account.name,
        balance=account.balance,
        equity=account.equity,
        currency=account.currency,
        last_sync_at=account.last_sync_at,
        last_sync_source=account.last_sync_source,
        total_deals=db.scalar(
            select(func.count()).select_from(Deal).where(Deal.account_id == account.id)
        ) or 0,
        total_trades=db.scalar(
            select(func.count()).select_from(Trade).where(Trade.account_id == account.id)
        ) or 0,
        open_trades=db.scalar(
            select(func.count())
            .select_from(Trade)
            .where(Trade.account_id == account.id, Trade.closed_at.is_(None))
        ) or 0,
        sync_mode=mode,
        connected=connected,
        phase=phase,
        credentials_configured=creds["configured"],
        message=message,
    )


@router.post("/sync", response_model=MT5IngestResponse)
def sync_now(
    _user: CurrentUser,
    db: DbSession,
    config: AppConfig,
    full: Annotated[bool, Query(description="Unused; kept so old clients do not break")] = False,
) -> MT5IngestResponse:
    """There is nothing to pull.

    Deals arrive when a terminal's Expert Advisor sends them, so this server
    never reaches out to MetaTrader. The endpoint stays because the UI has a
    refresh button, and answering plainly is friendlier than a 404.
    """
    del full
    if config["mt5"].get("sync_mode") == "off":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Sync is turned off. Import a statement, or set sync mode to 'ea'.",
        )
    account = get_default_account(db)
    return MT5IngestResponse(
        account_id=account.id if account else None,
        deals_received=0,
        deals_new=0,
        trades_upserted=0,
        message=(
            "Terminals push their own deals; there is nothing to pull. "
            "If nothing is arriving, check the terminal is running."
        ),
    )


@router.post("/rebuild")
def rebuild(_user: CurrentUser, db: DbSession, config: AppConfig) -> dict[str, int]:
    """Re-fold every stored deal into trades (journal fields are preserved)."""
    total = 0
    for account in db.scalars(select(Account)).all():
        total += rebuild_trades(
            db, account.id, config["risk"], config["general"]["timezone"]
        )
    db.commit()
    return {"trades": total}


@router.get("/logs")
def sync_logs(_user: CurrentUser, db: DbSession, limit: Annotated[int, Query(le=200)] = 20):
    return list(
        db.scalars(select(SyncLog).order_by(SyncLog.created_at.desc()).limit(limit)).all()
    )


# --- candles ----------------------------------------------------------------


_TIMEFRAME_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800,
}


@router.get("/candles", response_model=CandleResponse)
def get_candles(
    _user: CurrentUser,
    db: DbSession,
    config: AppConfig,
    symbol: str | None = None,
    timeframe: str = "M15",
    start: datetime | None = None,
    end: datetime | None = None,
    trade_id: int | None = None,
) -> CandleResponse:
    """Candles for the chart replay, from what terminals have already sent.

    Either ``trade_id`` (which picks the symbol and the window from the trade)
    or an explicit ``symbol`` is required.

    A terminal sends one timeframe, because the rest are arithmetic on it: ask
    for H1 and it is folded out of the M5 bars that are here. Ask for one below
    what was collected and there is nothing to answer with -- M1 cannot be
    recovered from M5 -- so the response says which timeframes this symbol can
    be drawn at rather than leaving the buttons to be discovered as empty.
    """
    if trade_id:
        trade = db.get(Trade, trade_id)
        if trade is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Trade not found")
        symbol = trade.symbol
        before, after = timeframes.window_padding(
            float(config["charts"].get("history_days_before", timeframes.DEFAULT_DAYS)),
            float(config["charts"].get("history_days_after", timeframes.DEFAULT_DAYS)),
        )
        start = trade.opened_at - before
        end = (trade.closed_at or trade.opened_at) + after

    if not symbol:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Provide either a trade_id or a symbol"
        )

    if start is None or end is None:
        end = end or datetime.now(timezone.utc).replace(tzinfo=None)
        start = start or end - timedelta(days=5)

    start = start.replace(tzinfo=None) if start.tzinfo else start
    end = end.replace(tzinfo=None) if end.tzinfo else end

    stored = [
        row
        for row in db.scalars(
            select(distinct(Candle.timeframe)).where(Candle.symbol == symbol)
        )
        if row
    ]
    # The collected timeframe wins over a derived one wherever both exist: it
    # came from the broker's own bars, including its idea of where a day
    # starts, which epoch-aligned buckets can only approximate.
    read = timeframe if timeframe in stored else timeframes.source_for(timeframe, stored)
    if read is None:
        return CandleResponse(
            symbol=symbol,
            timeframe=timeframe,
            source="none",
            available=timeframes.available(stored),
            candles=[],
        )

    rows = list(
        db.scalars(
            select(Candle)
            .where(
                Candle.symbol == symbol,
                Candle.timeframe == read,
                Candle.time >= start,
                Candle.time <= end,
            )
            .order_by(Candle.time)
        ).all()
    )

    bars = [
        timeframes.Bar(
            time=row.time.replace(tzinfo=timezone.utc),
            open=row.open,
            high=row.high,
            low=row.low,
            close=row.close,
            volume=row.volume,
        )
        for row in rows
    ]
    if read != timeframe:
        bars = timeframes.aggregate(bars, timeframe)

    return CandleResponse(
        symbol=symbol,
        timeframe=timeframe,
        # Named after where the bars came from, so a chart built out of M5 can
        # say so. Only what a terminal has sent is ever drawn: charts come from
        # the candles the Expert Advisor stores as it goes, and a period
        # nothing was running for simply has none.
        source="local" if read == timeframe else read,
        available=timeframes.available(stored),
        candles=[
            {
                "time": bar.time,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
            }
            for bar in bars
        ],
    )


def _timeframe_seconds(timeframe: str) -> int:
    return _TIMEFRAME_SECONDS.get(timeframe.upper(), 900)
