"""File-based import: MT5 HTML reports and generic CSV."""

from __future__ import annotations

from datetime import timezone
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..deps import AppConfig, CurrentUser, DbSession, get_default_account
from ..models import Account, SyncLog, Tag, Trade
from ..services.aggregation import (
    _infer_value_per_unit,
    compute_derived,
    resolve_account_size,
)
from ..services.importers import parse_mt5_html_report, parse_trades_csv

router = APIRouter(prefix="/import", tags=["import"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


@router.post("/file")
async def import_file(
    _user: CurrentUser,
    db: DbSession,
    config: AppConfig,
    file: Annotated[UploadFile, File()],
    account_id: Annotated[int | None, Form()] = None,
    dry_run: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is too large")

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("utf-16", errors="replace")

    name = (file.filename or "").lower()
    account_info: dict[str, Any] = {}
    if name.endswith((".html", ".htm")) or "<table" in content[:8000].lower():
        parsed = parse_mt5_html_report(content)
        positions = parsed["positions"]
        account_info = parsed["account"]
        kind = "mt5_html"
    else:
        try:
            positions = parse_trades_csv(content)
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
        kind = "csv"

    if not positions:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No trades were found in that file. For MetaTrader 5 use History -> Report -> "
            "save as HTML, or export a CSV with at least symbol, open time and price columns.",
        )

    if dry_run:
        return {
            "kind": kind,
            "dry_run": True,
            "found": len(positions),
            "account": account_info,
            "preview": positions[:10],
        }

    account = _target_account(db, account_id, account_info)
    created, updated = _persist_positions(db, account, positions, config)

    db.add(
        SyncLog(
            account_id=account.id,
            source=kind,
            status="ok",
            deals_received=len(positions),
            deals_new=created,
            trades_upserted=created + updated,
            message=file.filename or "",
        )
    )
    db.commit()

    return {
        "kind": kind,
        "dry_run": False,
        "found": len(positions),
        "created": created,
        "updated": updated,
        "account_id": account.id,
    }


def _target_account(
    db: Session, account_id: int | None, account_info: dict[str, Any]
) -> Account:
    if account_id:
        account = db.get(Account, account_id)
        if account is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Account not found")
        return account

    login = str(account_info.get("login") or "0")
    if login != "0":
        account = db.scalar(select(Account).where(Account.login == login))
        if account is not None:
            return account
        placeholder = db.scalar(select(Account).where(Account.login == "0"))
        if placeholder is not None:
            placeholder.login = login
            placeholder.name = placeholder.name or str(account_info.get("name") or "")
            placeholder.server = str(account_info.get("server") or placeholder.server)
            placeholder.currency = str(account_info.get("currency") or placeholder.currency)
            db.flush()
            return placeholder
        account = Account(
            login=login,
            name=str(account_info.get("name") or ""),
            server=str(account_info.get("server") or ""),
            currency=str(account_info.get("currency") or "USD"),
            is_default=db.scalar(select(func.count()).select_from(Account)) == 0,
        )
        db.add(account)
        db.flush()
        return account

    account = get_default_account(db)
    if account is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No account to import into")
    return account


def _persist_positions(
    db: Session, account: Account, positions: list[dict[str, Any]], config: dict[str, Any]
) -> tuple[int, int]:
    account_size = resolve_account_size(account, config["risk"])
    tz_name = config["general"]["timezone"]

    existing = {
        t.position_id: t
        for t in db.scalars(select(Trade).where(Trade.account_id == account.id)).unique().all()
    }
    tags_by_name = {t.name.lower(): t for t in db.scalars(select(Tag)).all()}

    created = updated = 0
    for item in positions:
        position_id = int(item["position_id"])
        trade = existing.get(position_id)
        if trade is None:
            trade = Trade(account_id=account.id, position_id=position_id, source="import")
            db.add(trade)
            existing[position_id] = trade
            created += 1
        else:
            updated += 1

        trade.symbol = item["symbol"]
        trade.direction = item["direction"]
        trade.opened_at = _naive(item["opened_at"])
        trade.closed_at = _naive(item.get("closed_at"))
        trade.volume = item["volume"]
        trade.closed_volume = item["volume"] if item.get("closed_at") else 0.0
        trade.entry_price = item["entry_price"]
        trade.exit_price = item.get("exit_price") or None
        trade.gross_profit = item.get("gross_profit", 0.0)
        trade.commission = item.get("commission", 0.0)
        trade.swap = item.get("swap", 0.0)

        if trade.stop_source != "manual":
            trade.initial_stop = item.get("initial_stop")
            trade.stop_source = "mt5" if item.get("initial_stop") else "none"
        if trade.target_source != "manual":
            trade.initial_target = item.get("initial_target")
            trade.target_source = "mt5" if item.get("initial_target") else "none"

        if trade.value_per_unit <= 0:
            trade.value_per_unit = _infer_value_per_unit(
                trade.direction,
                trade.entry_price,
                trade.exit_price,
                trade.closed_volume,
                trade.gross_profit,
            )

        if item.get("notes"):
            trade.notes = item["notes"]
        if item.get("setup"):
            trade.setup = item["setup"]
        if item.get("tags"):
            resolved = []
            for name in item["tags"]:
                tag = tags_by_name.get(name.lower())
                if tag is None:
                    tag = Tag(name=name, category="custom")
                    db.add(tag)
                    db.flush()
                    tags_by_name[name.lower()] = tag
                resolved.append(tag)
            trade.tags = resolved

        compute_derived(trade, config["risk"], account_size, tz_name)

    db.flush()
    return created, updated


def _naive(value):
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
