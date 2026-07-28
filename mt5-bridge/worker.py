"""One MetaTrader terminal, driven by one process.

The MetaTrader5 package keeps a single connection per *process*: importing it
twice in one interpreter does not give you two terminals, it gives you one
connection that the second caller quietly steals. Copying to several accounts
therefore needs several processes, and this is what each of them runs.

The worker speaks newline-delimited JSON on stdin and stdout — one request
object in, one response object out, strictly in order. That is deliberately
the dullest possible protocol: the supervisor can restart a wedged worker
without any shared state to clean up, and a worker that dies takes nothing
with it but its own terminal.

Every reply is ``{"ok": true, "result": ...}`` or ``{"ok": false, "error": ...}``.
Errors are returned, never raised: a broker refusing an order is an ordinary
outcome that the copier records and carries on from, not a crash.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - only true outside the Wine image
    mt5 = None  # type: ignore[assignment]


# Retcodes that mean "this order will never work", as opposed to "try again".
FATAL_RETCODES = {
    10004,  # requote
    10013,  # invalid request
    10014,  # invalid volume
    10015,  # invalid price
    10016,  # invalid stops
    10017,  # trade disabled
    10018,  # market closed
    10019,  # not enough money
    10027,  # autotrading disabled by client
    10030,  # unsupported filling mode
}


def _own_copy_of_terminal(shared_exe: str, data_path: str) -> str:
    """Give this account its own installation, copied once.

    Costs a few hundred megabytes and half a minute the first time an account
    is used, and nothing on every start after that.
    """
    target_dir = Path(data_path)
    target_exe = target_dir / "terminal64.exe"
    if target_exe.exists():
        return str(target_exe)

    source_dir = Path(shared_exe).parent
    if not source_dir.exists():
        raise OSError(f"no MetaTrader installation at {source_dir}")

    target_dir.mkdir(parents=True, exist_ok=True)
    # Skip the parts that are large, per-profile, and rebuilt on demand.
    shutil.copytree(
        source_dir,
        target_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("logs", "Tester", "Bases", "MQL5"),
    )
    if not target_exe.exists():
        raise OSError(f"the copy produced no terminal at {target_exe}")
    return str(target_exe)


class Worker:
    def __init__(self, account: dict[str, Any]) -> None:
        self.account = account
        self.connected = False
        self.error = ""

    # -- connection ------------------------------------------------------
    def connect(self, force: bool = False) -> bool:
        if not force and self.connected and mt5.terminal_info() is not None:
            return True

        self.connected = False
        login = str(self.account.get("login", "")).strip()
        server = str(self.account.get("server", "")).strip()
        password = self.account.get("password", "")
        terminal = self.account.get("terminal_path") or os.getenv("MT5_TERMINAL_PATH", "")
        data_path = self.account.get("data_path", "")

        # /portable makes MetaTrader keep its data *beside the executable*,
        # not in a directory of our choosing -- there is no option for the
        # latter. Two accounts therefore cannot share one installation without
        # fighting over the same profile, so each gets its own copy of the
        # terminal directory and runs that.
        if data_path:
            try:
                terminal = _own_copy_of_terminal(terminal, data_path)
            except OSError as exc:
                self.error = f"could not prepare a terminal for this account: {exc}"
                return False

        kwargs: dict[str, Any] = {"portable": True} if data_path else {}
        if terminal:
            kwargs["path"] = terminal

        if not mt5.initialize(**kwargs):
            self.error = f"could not start the terminal: {mt5.last_error()}"
            return False

        if login and server:
            try:
                ok = mt5.login(int(login), password=password, server=server)
            except ValueError:
                self.error = f"{login!r} is not a valid account number"
                return False
            if not ok:
                self.error = f"login refused: {mt5.last_error()}"
                mt5.shutdown()
                return False

        self.connected = True
        self.error = ""
        return True

    def require(self) -> None:
        if not self.connect():
            raise RuntimeError(self.error or "not connected")

    # -- reads -----------------------------------------------------------
    def account_info(self) -> dict[str, Any]:
        self.require()
        info = mt5.account_info()
        if info is None:
            raise RuntimeError(f"no account information: {mt5.last_error()}")
        return {
            "login": str(info.login),
            "name": info.name,
            "server": info.server,
            "currency": info.currency,
            "leverage": info.leverage,
            "balance": float(info.balance),
            "equity": float(info.equity),
            "margin": float(info.margin),
            "margin_free": float(info.margin_free),
            "profit": float(info.profit),
            "trade_allowed": bool(info.trade_allowed),
        }

    def positions(self) -> list[dict[str, Any]]:
        self.require()
        rows = mt5.positions_get() or []
        return [
            {
                "position_id": int(row.identifier or row.ticket),
                "ticket": int(row.ticket),
                "symbol": row.symbol,
                "direction": "long" if row.type == mt5.POSITION_TYPE_BUY else "short",
                "volume": float(row.volume),
                "open_price": float(row.price_open),
                "current_price": float(row.price_current),
                "stop_loss": float(row.sl) or None,
                "take_profit": float(row.tp) or None,
                "profit": float(row.profit),
                "swap": float(row.swap),
                "magic": int(row.magic),
                "comment": row.comment,
                "opened_at": int(row.time),
            }
            for row in rows
        ]

    def symbols(self) -> list[str]:
        self.require()
        return [row.name for row in (mt5.symbols_get() or [])]

    def symbol_spec(self, symbol: str) -> dict[str, Any]:
        self.require()
        info = mt5.symbol_info(symbol)
        if info is None:
            # An unwatched symbol has no specification until it is selected.
            mt5.symbol_select(symbol, True)
            info = mt5.symbol_info(symbol)
        if info is None:
            raise RuntimeError(f"this broker has no symbol {symbol!r}")

        tick_size = float(info.trade_tick_size) or float(info.point) or 0.0
        tick_value = float(info.trade_tick_value)
        return {
            "symbol": info.name,
            "digits": int(info.digits),
            "point": float(info.point),
            "volume_min": float(info.volume_min),
            "volume_max": float(info.volume_max),
            "volume_step": float(info.volume_step),
            "value_per_unit": (tick_value / tick_size) if tick_size else 0.0,
            "trade_mode": int(info.trade_mode),
            "filling_mode": int(info.filling_mode),
            "bid": float(info.bid),
            "ask": float(info.ask),
        }

    # -- writes ----------------------------------------------------------
    def _filling(self, symbol: str) -> int:
        """The filling mode this symbol will actually accept.

        Brokers differ, and sending the wrong one is rejected with 10030
        rather than corrected, so ask the symbol instead of assuming.
        """
        info = mt5.symbol_info(symbol)
        mode = int(getattr(info, "filling_mode", 0) or 0)
        if mode & 2:
            return mt5.ORDER_FILLING_IOC
        if mode & 1:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    def open_position(
        self,
        symbol: str,
        direction: str,
        volume: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        comment: str = "TradeZulu",
        deviation: int = 20,
        magic: int = 0,
    ) -> dict[str, Any]:
        self.require()
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"could not select {symbol}")

        info = mt5.symbol_info_tick(symbol)
        if info is None:
            raise RuntimeError(f"no price for {symbol}")

        is_long = direction == "long"
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": mt5.ORDER_TYPE_BUY if is_long else mt5.ORDER_TYPE_SELL,
            "price": float(info.ask if is_long else info.bid),
            "deviation": int(deviation),
            "magic": int(magic),
            "comment": comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(symbol),
        }
        if stop_loss:
            request["sl"] = float(stop_loss)
        if take_profit:
            request["tp"] = float(take_profit)

        return self._send(request)

    def close_position(self, ticket: int, volume: float | None = None) -> dict[str, Any]:
        self.require()
        rows = mt5.positions_get(ticket=int(ticket))
        if not rows:
            # Already gone. That is the desired end state, so say so plainly
            # rather than failing a close that has nothing left to close.
            return {"retcode": 0, "closed": True, "note": "the position was already closed"}

        position = rows[0]
        is_long = position.type == mt5.POSITION_TYPE_BUY
        tick = mt5.symbol_info_tick(position.symbol)
        if tick is None:
            raise RuntimeError(f"no price for {position.symbol}")

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": position.symbol,
            "volume": float(volume or position.volume),
            "type": mt5.ORDER_TYPE_SELL if is_long else mt5.ORDER_TYPE_BUY,
            "position": int(position.ticket),
            "price": float(tick.bid if is_long else tick.ask),
            "deviation": 20,
            "magic": int(position.magic),
            "comment": "TradeZulu close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": self._filling(position.symbol),
        }
        return self._send(request)

    def modify_position(
        self, ticket: int, stop_loss: float | None, take_profit: float | None
    ) -> dict[str, Any]:
        self.require()
        rows = mt5.positions_get(ticket=int(ticket))
        if not rows:
            return {"retcode": 0, "note": "the position is no longer open"}

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": rows[0].symbol,
            "position": int(ticket),
            "sl": float(stop_loss or 0.0),
            "tp": float(take_profit or 0.0),
        }
        return self._send(request)

    def _send(self, request: dict[str, Any]) -> dict[str, Any]:
        result = mt5.order_send(request)
        if result is None:
            raise RuntimeError(f"the terminal rejected the order outright: {mt5.last_error()}")

        payload = {
            "retcode": int(result.retcode),
            "deal": int(result.deal),
            "order": int(result.order),
            "volume": float(result.volume),
            "price": float(result.price),
            "comment": result.comment,
            "ok": result.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED),
        }
        if not payload["ok"]:
            payload["fatal"] = int(result.retcode) in FATAL_RETCODES
        return payload


def main() -> int:
    if mt5 is None:
        print(json.dumps({"ok": False, "error": "MetaTrader5 is not importable"}), flush=True)
        return 1

    account = json.loads(os.environ.get("WORKER_ACCOUNT", "{}"))
    worker = Worker(account)

    handlers = {
        "ping": lambda **_: {"alive": True, "connected": worker.connected},
        "connect": lambda **kw: {"connected": worker.connect(force=kw.get("force", False)),
                                 "error": worker.error},
        "account": lambda **_: worker.account_info(),
        "positions": lambda **_: worker.positions(),
        "symbols": lambda **_: worker.symbols(),
        "symbol_spec": lambda **kw: worker.symbol_spec(kw["symbol"]),
        "open": lambda **kw: worker.open_position(**kw),
        "close": lambda **kw: worker.close_position(**kw),
        "modify": lambda **kw: worker.modify_position(**kw),
    }

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        started = time.time()
        try:
            request = json.loads(line)
            command = request.get("command", "")
            handler = handlers.get(command)
            if handler is None:
                raise RuntimeError(f"unknown command {command!r}")
            reply = {"ok": True, "result": handler(**request.get("args", {}))}
        except Exception as exc:  # noqa: BLE001 - the protocol *is* the error channel
            reply = {"ok": False, "error": str(exc)}
        reply["ms"] = int((time.time() - started) * 1000)
        print(json.dumps(reply), flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
