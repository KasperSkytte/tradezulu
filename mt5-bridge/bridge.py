"""HTTP bridge in front of the MetaTrader5 Python package.

Runs *inside* Wine next to a headless MetaTrader 5 terminal and exposes the
handful of read-only endpoints TradeZulu's pull sync needs:

    GET /health
    GET /account
    GET /deals?from_ts=&to_ts=
    GET /candles?symbol=&timeframe=&from_ts=&to_ts=

Only ever reads. Log in with the *investor* password if your broker offers
one — it is read-only by construction, so this container can never trade.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - only importable under Wine
    print("MetaTrader5 package is missing. This must run under the Wine Python.")
    raise

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-8s %(message)s",
)
log = logging.getLogger("mt5-bridge")

LOGIN = os.getenv("MT5_LOGIN", "").strip()
PASSWORD = os.getenv("MT5_PASSWORD", "").strip()
SERVER = os.getenv("MT5_SERVER", "").strip()
TERMINAL = os.getenv("MT5_TERMINAL_PATH", "").strip()
PORT = int(os.getenv("BRIDGE_PORT", "8080"))

TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
}

_lock = threading.Lock()
_connected = False


def connect() -> bool:
    """Initialise the terminal connection, reconnecting if it dropped."""
    global _connected
    with _lock:
        if _connected and mt5.terminal_info() is not None:
            return True

        kwargs: dict = {}
        if TERMINAL:
            kwargs["path"] = TERMINAL
        if LOGIN and PASSWORD and SERVER:
            kwargs.update(login=int(LOGIN), password=PASSWORD, server=SERVER)

        mt5.shutdown()
        if not mt5.initialize(**kwargs):
            log.error("initialize() failed: %s", mt5.last_error())
            _connected = False
            return False

        info = mt5.account_info()
        if info is None:
            log.error("account_info() is empty: %s", mt5.last_error())
            _connected = False
            return False

        log.info("connected to %s as %s (%s)", info.server, info.login, info.currency)
        _connected = True
        return True


def account_payload() -> dict:
    info = mt5.account_info()
    if info is None:
        return {}
    return {
        "login": str(info.login),
        "name": info.name,
        "server": info.server,
        "company": info.company,
        "currency": info.currency,
        "leverage": int(info.leverage),
        "balance": float(info.balance),
        "equity": float(info.equity),
    }


def _value_per_unit(symbol: str) -> tuple[float, int]:
    """Money per one whole price unit for one lot, plus the symbol's digits."""
    info = mt5.symbol_info(symbol)
    if info is None:
        mt5.symbol_select(symbol, True)
        info = mt5.symbol_info(symbol)
    if info is None or not info.trade_tick_size:
        return 0.0, 5
    return float(info.trade_tick_value) / float(info.trade_tick_size), int(info.digits)


def deals_payload(from_ts: int, to_ts: int) -> list[dict]:
    start = datetime.fromtimestamp(from_ts, tz=timezone.utc)
    end = datetime.fromtimestamp(to_ts, tz=timezone.utc)

    deals = mt5.history_deals_get(start, end)
    if deals is None:
        log.warning("history_deals_get returned nothing: %s", mt5.last_error())
        return []

    # Stop losses live on the entry *order*, so pull the orders for the same
    # window once and index them by ticket.
    orders = mt5.history_orders_get(start, end) or []
    order_levels = {order.ticket: (float(order.sl), float(order.tp)) for order in orders}

    cache: dict[str, tuple[float, int]] = {}
    out: list[dict] = []
    for deal in deals:
        symbol = deal.symbol or ""
        if symbol and symbol not in cache:
            cache[symbol] = _value_per_unit(symbol)
        value_per_unit, digits = cache.get(symbol, (0.0, 5))

        sl, tp = order_levels.get(deal.order, (0.0, 0.0)) if deal.entry == 0 else (0.0, 0.0)

        out.append(
            {
                "ticket": int(deal.ticket),
                "order": int(deal.order),
                "position_id": int(deal.position_id),
                "symbol": symbol,
                "type": int(deal.type),
                "entry": int(deal.entry),
                "volume": float(deal.volume),
                "price": float(deal.price),
                "profit": float(deal.profit),
                "commission": float(deal.commission),
                "swap": float(deal.swap),
                "fee": float(deal.fee),
                "sl": sl,
                "tp": tp,
                "magic": int(deal.magic),
                "comment": deal.comment or "",
                "time": int(deal.time),
                "value_per_unit": value_per_unit,
                "digits": digits,
            }
        )
    return out


def candles_payload(symbol: str, timeframe: str, from_ts: int, to_ts: int) -> list[dict]:
    period = TIMEFRAMES.get(timeframe.upper(), mt5.TIMEFRAME_M15)
    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_range(
        symbol,
        period,
        datetime.fromtimestamp(from_ts, tz=timezone.utc),
        datetime.fromtimestamp(to_ts, tz=timezone.utc),
    )
    if rates is None:
        return []
    return [
        {
            "time": int(rate["time"]),
            "open": float(rate["open"]),
            "high": float(rate["high"]),
            "low": float(rate["low"]),
            "close": float(rate["close"]),
            "volume": float(rate["tick_volume"]),
        }
        for rate in rates
    ]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        log.debug(fmt, *args)

    def _respond(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        url = urlparse(self.path)
        query = parse_qs(url.query)

        def number(name: str, default: int) -> int:
            try:
                return int(query.get(name, [default])[0])
            except (TypeError, ValueError):
                return default

        if url.path == "/health":
            ok = connect()
            self._respond(
                {"status": "ok" if ok else "disconnected", "connected": ok},
                200 if ok else 503,
            )
            return

        if not connect():
            self._respond({"error": "not connected to MetaTrader 5"}, 503)
            return

        try:
            if url.path == "/account":
                self._respond(account_payload())
            elif url.path == "/deals":
                default_from = int((datetime.now(timezone.utc) - timedelta(days=730)).timestamp())
                self._respond(
                    deals_payload(
                        number("from_ts", default_from),
                        number("to_ts", int(time.time()) + 3600),
                    )
                )
            elif url.path == "/candles":
                symbol = query.get("symbol", [""])[0]
                if not symbol:
                    self._respond({"error": "symbol is required"}, 400)
                    return
                self._respond(
                    {
                        "symbol": symbol,
                        "timeframe": query.get("timeframe", ["M15"])[0],
                        "candles": candles_payload(
                            symbol,
                            query.get("timeframe", ["M15"])[0],
                            number("from_ts", int(time.time()) - 86400 * 5),
                            number("to_ts", int(time.time())),
                        ),
                    }
                )
            else:
                self._respond({"error": "not found"}, 404)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("request failed")
            self._respond({"error": str(exc)}, 500)


def main() -> int:
    log.info("MT5 bridge starting on port %s", PORT)
    for attempt in range(1, 31):
        if connect():
            break
        log.info("terminal not ready yet (attempt %d/30), waiting…", attempt)
        time.sleep(10)
    else:
        log.error("Could not reach MetaTrader 5. Check MT5_LOGIN/MT5_PASSWORD/MT5_SERVER.")

    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
