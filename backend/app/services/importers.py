"""Importers for people who cannot (or will not) run the Expert Advisor.

Two formats are understood:

* the HTML trade report MetaTrader 5 writes from *History -> Report*, whose
  "Positions" table already is trade-level data;
* a generic CSV, either trade-level or deal-level, with flexible headers.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any

NBSP = " "
NNBSP = " "


class _TableRowParser(HTMLParser):
    """Collect every table row as a list of cell strings."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append("".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _clean_number(text: str) -> float:
    text = (text or "").replace(NBSP, "").replace(NNBSP, "").replace(" ", "").replace(",", "")
    text = text.replace("−", "-")  # MT5 sometimes emits a unicode minus
    if not text or text in {"-", "--"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


DATE_PATTERNS = (
    "%Y.%m.%d %H:%M:%S",
    "%Y.%m.%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%d.%m.%Y %H:%M:%S",
    "%m/%d/%Y %H:%M:%S",
)


def _parse_dt(text: str) -> datetime | None:
    text = (text or "").replace(NBSP, " ").strip()
    if not text:
        return None
    for pattern in DATE_PATTERNS:
        try:
            return datetime.strptime(text, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_mt5_html_report(content: str) -> dict[str, Any]:
    """Extract account info and positions from an MT5 HTML report."""
    parser = _TableRowParser()
    parser.feed(content)

    account: dict[str, Any] = {"login": "0", "server": "", "name": "", "currency": "USD"}
    positions: list[dict[str, Any]] = []
    section = ""

    for row in parser.rows:
        cells = [c.replace(NBSP, " ").strip() for c in row if c.replace(NBSP, " ").strip() != ""]
        if not cells:
            continue

        # Header block: "Account: 12345 (Name, Broker-Server, ...)"
        joined = " ".join(cells)
        if account["login"] == "0":
            match = re.search(r"Account:?\s*([0-9]{4,})", joined)
            if match:
                account["login"] = match.group(1)
                rest = re.search(r"Account:?\s*[0-9]{4,}\s*\(([^)]*)\)", joined)
                if rest:
                    parts = [p.strip() for p in rest.group(1).split(",")]
                    if parts:
                        account["name"] = parts[0]
                    if len(parts) > 1:
                        account["currency"] = parts[1][:8]
                    if len(parts) > 2:
                        account["server"] = parts[2]
        if account["server"] == "":
            match = re.search(r"Broker:?\s*(.+)", joined)
            if match:
                account["server"] = match.group(1).strip()[:120]

        if len(cells) == 1:
            label = cells[0].lower().strip(":")
            if label in {"positions", "orders", "deals", "results", "summary"}:
                section = label
            continue

        if section != "positions":
            continue
        # Skip the column-header row and any summary rows.
        if cells[0].lower().startswith("time") or len(row) < 13:
            continue

        opened_at = _parse_dt(row[0])
        if opened_at is None:
            continue

        try:
            direction_text = row[3].strip().lower()
            if direction_text not in ("buy", "sell"):
                continue
            positions.append(
                {
                    "position_id": int(_clean_number(row[1])),
                    "symbol": row[2].strip().upper(),
                    "direction": "long" if direction_text == "buy" else "short",
                    "volume": _clean_number(row[4]),
                    "entry_price": _clean_number(row[5]),
                    "initial_stop": _clean_number(row[6]) or None,
                    "initial_target": _clean_number(row[7]) or None,
                    "opened_at": opened_at,
                    "closed_at": _parse_dt(row[8]),
                    "exit_price": _clean_number(row[9]),
                    "commission": _clean_number(row[10]),
                    "swap": _clean_number(row[11]),
                    "gross_profit": _clean_number(row[12]),
                }
            )
        except (IndexError, ValueError):
            continue

    return {"account": account, "positions": positions}


# --- CSV --------------------------------------------------------------------

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "position_id": ("position", "position_id", "positionid", "ticket", "id", "trade_id"),
    "symbol": ("symbol", "instrument", "market", "pair"),
    "direction": ("direction", "type", "side", "buy/sell", "long/short"),
    "volume": ("volume", "size", "lots", "quantity", "qty"),
    "entry_price": ("entry", "entry_price", "openprice", "open_price", "price_open", "price"),
    "exit_price": ("exit", "exit_price", "closeprice", "close_price", "price_close"),
    "opened_at": ("opentime", "open_time", "open time", "time_open", "opened_at", "entrytime", "date"),
    "closed_at": ("closetime", "close_time", "close time", "time_close", "closed_at", "exittime"),
    "initial_stop": ("sl", "s/l", "stop", "stoploss", "stop_loss", "initial_stop"),
    "initial_target": ("tp", "t/p", "target", "takeprofit", "take_profit", "initial_target"),
    "gross_profit": ("profit", "grossprofit", "gross_profit", "pnl", "p/l", "net"),
    "commission": ("commission", "commissions", "fee", "fees"),
    "swap": ("swap", "rollover", "interest"),
    "notes": ("notes", "comment", "note"),
    "setup": ("setup", "strategy"),
    "tags": ("tags", "tag"),
}


def _normalise_header(name: str) -> str:
    return re.sub(r"[^a-z0-9/_ ]", "", (name or "").strip().lower())


def _build_column_map(headers: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    normalised = [_normalise_header(h) for h in headers]
    for field, aliases in COLUMN_ALIASES.items():
        for index, header in enumerate(normalised):
            if header in aliases and field not in mapping:
                mapping[field] = index
                break
    return mapping


def parse_trades_csv(content: str) -> list[dict[str, Any]]:
    """Parse a trade-level CSV into position dicts."""
    text = content.lstrip("﻿")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)

    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        return []

    mapping = _build_column_map(rows[0])
    if "symbol" not in mapping:
        raise ValueError("Could not find a symbol column in the CSV")

    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows[1:], start=1):
        def cell(field: str, default: str = "", row: list[str] = row) -> str:
            position = mapping.get(field)
            if position is None or position >= len(row):
                return default
            return row[position].strip()

        symbol = cell("symbol").upper()
        if not symbol:
            continue

        direction_raw = cell("direction").lower()
        if direction_raw.startswith(("b", "l")):
            direction = "long"
        elif direction_raw.startswith(("s",)):
            direction = "short"
        else:
            direction = "long"

        opened_at = _parse_dt(cell("opened_at"))
        if opened_at is None:
            continue

        out.append(
            {
                "position_id": int(_clean_number(cell("position_id"))) or -index,
                "symbol": symbol,
                "direction": direction,
                "volume": _clean_number(cell("volume")) or 1.0,
                "entry_price": _clean_number(cell("entry_price")),
                "exit_price": _clean_number(cell("exit_price")) or None,
                "opened_at": opened_at,
                "closed_at": _parse_dt(cell("closed_at")),
                "initial_stop": _clean_number(cell("initial_stop")) or None,
                "initial_target": _clean_number(cell("initial_target")) or None,
                "gross_profit": _clean_number(cell("gross_profit")),
                "commission": _clean_number(cell("commission")),
                "swap": _clean_number(cell("swap")),
                "notes": cell("notes"),
                "setup": cell("setup"),
                "tags": [t.strip() for t in cell("tags").replace("|", ",").split(",") if t.strip()],
            }
        )
    return out
