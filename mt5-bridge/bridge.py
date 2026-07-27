"""HTTP bridge in front of the MetaTrader5 Python package.

Runs *inside* Wine next to a headless MetaTrader 5 terminal. MetaTrader's
client-server protocol is proprietary, so a real terminal is the only way to
reach a trading account with nothing but a server, a login and a password —
this container is that terminal, kept out of sight.

    GET  /health                     is the terminal up and logged in?
    POST /connect                    log in with {server, login, password}
    POST /disconnect                 log out and forget the credentials
    GET  /account                    balance, currency, leverage
    GET  /deals?from_ts=&to_ts=      deal history
    GET  /candles?symbol=&...        OHLC for the replay chart

Everything is read-only: no endpoint can place, modify or close an order.
Log in with the broker's *investor* password and that is guaranteed rather
than merely intended.
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

TERMINAL = os.getenv("MT5_TERMINAL_PATH", "").strip()
PORT = int(os.getenv("BRIDGE_PORT", "8080"))
# Optional shared secret. The bridge is not published outside the compose
# network, but defence in depth is free.
TOKEN = os.getenv("BRIDGE_TOKEN", "").strip()

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


class Terminal:
    """Owns the single MetaTrader connection and the credentials in use."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connected = False
        self._error = ""
        self._credentials: dict[str, str] = {
            "server": os.getenv("MT5_SERVER", "").strip(),
            "login": os.getenv("MT5_LOGIN", "").strip(),
            "password": os.getenv("MT5_PASSWORD", "").strip(),
        }

    # -- state -----------------------------------------------------------
    @property
    def error(self) -> str:
        return self._error

    @property
    def has_credentials(self) -> bool:
        return all(self._credentials.get(field) for field in ("server", "login", "password"))

    def describe(self) -> dict:
        return {
            "connected": self._connected,
            "configured": self.has_credentials,
            "server": self._credentials.get("server", ""),
            "login": self._credentials.get("login", ""),
            "error": self._error,
        }

    # -- connection ------------------------------------------------------
    def set_credentials(self, server: str, login: str, password: str) -> None:
        with self._lock:
            self._credentials = {
                "server": server.strip(),
                "login": str(login).strip(),
                "password": password,
            }
            self._connected = False
            mt5.shutdown()

    def disconnect(self) -> None:
        with self._lock:
            mt5.shutdown()
            self._connected = False
            self._credentials = {"server": "", "login": "", "password": ""}
            self._error = ""

    def ensure(self, force: bool = False) -> bool:
        """Connect if needed. Safe to call on every request."""
        with self._lock:
            if not force and self._connected and mt5.terminal_info() is not None:
                return True

            if not self.has_credentials:
                self._error = (
                    "No account configured. Enter the server, login and investor "
                    "password in TradeZulu under Settings -> MetaTrader 5."
                )
                self._connected = False
                return False

            kwargs: dict = {
                "login": int(self._credentials["login"]),
                "password": self._credentials["password"],
                "server": self._credentials["server"],
                # Long enough for the terminal to start and reach the broker.
                "timeout": int(os.getenv("MT5_INIT_TIMEOUT_MS", "120000")),
            }
            if TERMINAL:
                kwargs["path"] = TERMINAL

            mt5.shutdown()
            if not mt5.initialize(**kwargs):
                code, message = mt5.last_error()
                self._error = self._explain(code, message)
                log.error("initialize() failed: %s (%s)", message, code)
                self._connected = False
                return False

            info = mt5.account_info()
            if info is None:
                code, message = mt5.last_error()
                self._error = self._explain(code, message)
                self._connected = False
                return False

            log.info("connected to %s as %s (%s)", info.server, info.login, info.currency)
            self._error = ""
            self._connected = True
            return True

    @staticmethod
    def _explain(code: int, message: str) -> str:
        """Turn MetaTrader's terse errors into something actionable."""
        hints = {
            -6: "The broker rejected the login. Check the account number, the "
                "password and that the server name matches exactly.",
            -8: "The terminal did not answer in time. It may still be starting "
                "up — try again in a minute.",
            -10: "The terminal could not be started. Check the container logs.",
            -2: "The terminal is not installed where the bridge expects it.",
        }
        hint = hints.get(code)
        return f"{message} ({code}){'. ' + hint if hint else ''}"


terminal = Terminal()


# --- payload builders -------------------------------------------------------


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
        # Investor logins report trade_allowed = False, which is what we want.
        "trade_allowed": bool(getattr(info, "trade_allowed", False)),
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


# --- HTTP -------------------------------------------------------------------


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

    def _authorised(self) -> bool:
        if not TOKEN:
            return True
        if self.headers.get("X-Bridge-Token", "") == TOKEN:
            return True
        self._respond({"error": "unauthorised"}, 401)
        return False

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    # -- routes ----------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler naming
        if not self._authorised():
            return
        path = urlparse(self.path).path

        if path == "/connect":
            body = self._read_json()
            server = str(body.get("server") or "").strip()
            login = str(body.get("login") or "").strip()
            password = str(body.get("password") or "")
            if not (server and login and password):
                self._respond({"error": "server, login and password are all required"}, 400)
                return

            terminal.set_credentials(server, login, password)
            if terminal.ensure(force=True):
                self._respond({"ok": True, "account": account_payload()})
            else:
                self._respond({"ok": False, "error": terminal.error}, 502)
            return

        if path == "/disconnect":
            terminal.disconnect()
            self._respond({"ok": True})
            return

        self._respond({"error": "not found"}, 404)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler naming
        if not self._authorised():
            return

        url = urlparse(self.path)
        query = parse_qs(url.query)

        def number(name: str, default: int) -> int:
            try:
                return int(query.get(name, [default])[0])
            except (TypeError, ValueError):
                return default

        if url.path == "/health":
            # Always 200: "reachable but not logged in" is a distinct state
            # from "not reachable", and the UI needs to tell them apart.
            connected = terminal.ensure() if terminal.has_credentials else False
            payload = terminal.describe()
            payload["status"] = "ok" if connected else "disconnected"
            if connected:
                payload["account"] = account_payload()
            self._respond(payload)
            return

        if not terminal.ensure():
            self._respond({"error": terminal.error or "not connected"}, 503)
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
                timeframe = query.get("timeframe", ["M15"])[0]
                self._respond(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "candles": candles_payload(
                            symbol,
                            timeframe,
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
    log.info("MT5 bridge listening on port %s", PORT)
    if terminal.has_credentials:
        log.info("credentials supplied by environment; connecting")
        terminal.ensure()
    else:
        log.info("waiting for credentials from TradeZulu (Settings -> MetaTrader 5)")

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
