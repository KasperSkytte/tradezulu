"""MetaTrader 5 synchronisation.

Two directions are supported and they can be used at the same time:

* **push** - the ``TradeZuluSync`` Expert Advisor running inside your terminal
  POSTs new deals to ``/api/mt5/ingest`` using an API key. Nothing needs to be
  reachable from the server side, and no broker credentials are stored here.
* **pull** - an optional ``mt5-bridge`` container runs the MetaTrader5 Python
  package next to a headless terminal; the Sync button asks it for new deals.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import AppConfig, CurrentUser, DbSession, get_default_account, require_ingest_auth
from ..models import Account, Candle, Deal, SyncLog, Trade
from ..schemas import (
    CandleResponse,
    MT5IngestRequest,
    MT5IngestResponse,
    SyncStatus,
)
from ..services.aggregation import (
    _parse_time,
    rebuild_trades,
    upsert_deals,
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
        account = Account(login=login, server=server, is_default=False)
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
    """Receive deals pushed by the TradeZuluSync Expert Advisor."""
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


@router.get("/status", response_model=SyncStatus)
def status_(_user: CurrentUser, db: DbSession, config: AppConfig) -> SyncStatus:
    account = get_default_account(db)
    mode = config["mt5"].get("sync_mode", "ea")

    bridge_reachable: bool | None = None
    message = ""
    if mode == "bridge":
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{config['mt5']['bridge_url'].rstrip('/')}/health")
                bridge_reachable = response.status_code == 200
                if not bridge_reachable:
                    message = f"Bridge responded with HTTP {response.status_code}"
        except httpx.HTTPError as exc:
            bridge_reachable = False
            message = f"Bridge unreachable: {exc}"

    if account is None:
        return SyncStatus(
            account_id=None, login=None, name=None, balance=None, equity=None, currency=None,
            last_sync_at=None, last_sync_source=None, total_deals=0, total_trades=0,
            open_trades=0, sync_mode=mode, bridge_reachable=bridge_reachable, message=message,
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
        bridge_reachable=bridge_reachable,
        message=message,
    )


@router.post("/sync", response_model=MT5IngestResponse)
def sync_now(
    _user: CurrentUser,
    db: DbSession,
    config: AppConfig,
    full: Annotated[bool, Query(description="Re-pull the whole history window")] = False,
) -> MT5IngestResponse:
    """Pull new deals from the optional MT5 bridge container."""
    mt5_cfg = config["mt5"]
    if mt5_cfg.get("sync_mode") != "bridge":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Pull sync is disabled. Set MT5 sync mode to 'bridge' in Settings, or let the "
            "TradeZuluSync Expert Advisor push deals to this server.",
        )

    base = str(mt5_cfg.get("bridge_url", "")).rstrip("/")
    if not base:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No bridge URL configured")

    account = get_default_account(db)
    if full or account is None or account.last_sync_at is None:
        days = int(mt5_cfg.get("history_days_on_full_sync", 730))
        since = datetime.now(timezone.utc) - timedelta(days=days)
    else:
        # Overlap by a day so late-settling swaps are picked up.
        since = account.last_sync_at.replace(tzinfo=timezone.utc) - timedelta(days=1)

    timeout = float(mt5_cfg.get("bridge_timeout_seconds", 60))
    try:
        with httpx.Client(timeout=timeout) as client:
            info = client.get(f"{base}/account").json()
            deals = client.get(
                f"{base}/deals", params={"from_ts": int(since.timestamp())}
            ).json()
    except httpx.HTTPError as exc:
        db.add(SyncLog(source="bridge", status="error", message=str(exc)))
        db.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Could not reach the MT5 bridge: {exc}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Bridge returned invalid JSON: {exc}"
        ) from exc

    if isinstance(deals, dict):
        deals = deals.get("deals", [])
    return _apply_ingest(db, config, info, deals, [], source="bridge")


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
    """Candles for the chart replay, from our cache or the bridge if configured.

    Either ``trade_id`` (which picks the symbol and the window from the trade)
    or an explicit ``symbol`` is required.
    """
    if trade_id:
        trade = db.get(Trade, trade_id)
        if trade is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Trade not found")
        symbol = trade.symbol
        span = _timeframe_seconds(timeframe)
        before = int(config["charts"].get("candles_before", 120))
        after = int(config["charts"].get("candles_after", 60))
        start = trade.opened_at - timedelta(seconds=span * before)
        end = (trade.closed_at or trade.opened_at) + timedelta(seconds=span * after)

    if not symbol:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Provide either a trade_id or a symbol"
        )

    if start is None or end is None:
        end = end or datetime.now(timezone.utc).replace(tzinfo=None)
        start = start or end - timedelta(days=5)

    start = start.replace(tzinfo=None) if start.tzinfo else start
    end = end.replace(tzinfo=None) if end.tzinfo else end

    rows = list(
        db.scalars(
            select(Candle)
            .where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.time >= start,
                Candle.time <= end,
            )
            .order_by(Candle.time)
        ).all()
    )
    source = "local"

    if not rows and config["mt5"].get("sync_mode") == "bridge":
        fetched = _fetch_candles_from_bridge(db, config, symbol, timeframe, start, end)
        if fetched:
            db.commit()
            rows = fetched
            source = "bridge"

    return CandleResponse(
        symbol=symbol,
        timeframe=timeframe,
        source=source,
        candles=[
            {
                "time": c.time.replace(tzinfo=timezone.utc),
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in rows
        ],
    )


def _fetch_candles_from_bridge(
    db: Session,
    config: dict[str, Any],
    symbol: str,
    timeframe: str,
    start: datetime,
    end: datetime,
) -> list[Candle]:
    base = str(config["mt5"].get("bridge_url", "")).rstrip("/")
    if not base:
        return []
    try:
        with httpx.Client(timeout=float(config["mt5"].get("bridge_timeout_seconds", 60))) as client:
            payload = client.get(
                f"{base}/candles",
                params={
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "from_ts": int(start.replace(tzinfo=timezone.utc).timestamp()),
                    "to_ts": int(end.replace(tzinfo=timezone.utc).timestamp()),
                },
            ).json()
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Candle fetch from bridge failed: %s", exc)
        return []

    candles = payload.get("candles", payload) if isinstance(payload, dict) else payload
    if not candles:
        return []
    _store_candles(db, [{"symbol": symbol, "timeframe": timeframe, "candles": candles}])
    return list(
        db.scalars(
            select(Candle)
            .where(
                Candle.symbol == symbol,
                Candle.timeframe == timeframe,
                Candle.time >= start,
                Candle.time <= end,
            )
            .order_by(Candle.time)
        ).all()
    )


_TIMEFRAME_SECONDS = {
    "M1": 60, "M5": 300, "M15": 900, "M30": 1800,
    "H1": 3600, "H4": 14400, "D1": 86400, "W1": 604800,
}


def _timeframe_seconds(timeframe: str) -> int:
    return _TIMEFRAME_SECONDS.get(timeframe.upper(), 900)
