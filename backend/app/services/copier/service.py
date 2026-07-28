"""The background loop that keeps the slaves in step with the master.

One pass reads the master's open positions once, then runs every enabled slave
against that same snapshot. Reading the master once per pass rather than once
per slave matters for more than speed: it means every slave decides from an
identical picture, so two accounts can never disagree about what the master
was holding.

The loop is intentionally boring and defensive:

* it never raises out of a pass — a broken slave is logged and skipped, and
  the next pass tries again,
* it holds no state between passes beyond what is in the database, so a
  restart resumes cleanly, and
* it does nothing at all unless at least one slave is enabled, so an install
  that only uses the journal pays nothing for the copier existing.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import select

from ...db import SessionLocal
from ...models import Account
from ..credentials import get_credentials
from ..crypto import decrypt
from .bridge_broker import BridgeBroker, BrokerUnavailable
from .runner import run_cycle

log = logging.getLogger(__name__)

DEFAULT_INTERVAL = 2.0


def enabled_slaves(db) -> list[Account]:
    return list(
        db.scalars(
            select(Account).where(Account.role == "slave", Account.copy_enabled.is_(True))
        )
    )


def sync_pool(broker: BridgeBroker, master: Account, master_credentials: dict[str, str],
              slaves: list[Account]) -> None:
    """Make the bridge hold a terminal for the master and every live slave.

    The master needs one too: the copier reads its open positions through the
    same pool, and its investor password is enough for that. Dry-run slaves are
    deliberately included, because watching what an account *would* do is only
    meaningful against its real balance and its own symbol list.
    """
    accounts = [
        {
            "id": str(master.id),
            "login": master_credentials.get("login", "") or master.login,
            "server": master_credentials.get("server", "") or master.server,
            "password": master_credentials.get("password", ""),
        }
    ]
    accounts += [
        {
            "id": str(slave.id),
            "login": slave.login,
            "server": slave.server,
            "password": decrypt(slave.password_enc or ""),
        }
        for slave in slaves
    ]
    broker.configure(accounts)


def run_once(bridge_url: str, token: str = "") -> dict[str, int]:
    """One pass over every enabled slave. Returns a small summary."""
    summary = {"slaves": 0, "opened": 0, "skipped": 0, "failed": 0, "halted": 0}

    with SessionLocal() as db:
        slaves = enabled_slaves(db)
        if not slaves:
            return summary

        master = db.scalar(select(Account).where(Account.role == "master"))
        if master is None:
            log.debug("copier: no master account, nothing to copy from")
            return summary

        broker = BridgeBroker(bridge_url, token)

        try:
            sync_pool(broker, master, get_credentials(db), slaves)
            master_rows = broker.positions(master.id)
        except BrokerUnavailable as exc:
            # Nothing can be decided without the master's positions, and
            # guessing would be worse than waiting for the next pass.
            log.warning("copier: %s", exc)
            return summary

        for slave in slaves:
            summary["slaves"] += 1
            try:
                result = run_cycle(db, master, slave, broker, master_rows)
                summary["opened"] += result.executed
                summary["skipped"] += result.skipped
                summary["failed"] += result.failed
                summary["halted"] += int(result.halted)
            except BrokerUnavailable as exc:
                log.warning("copier: account %s unavailable: %s", slave.id, exc)
            except Exception:  # noqa: BLE001 - one slave must not stop the others
                log.exception("copier: account %s failed", slave.id)

        db.commit()

    return summary


class CopierLoop:
    """Runs :func:`run_once` on a timer, in a thread."""

    def __init__(self, bridge_url_provider, token: str = "", interval: float = DEFAULT_INTERVAL):
        self._url_for = bridge_url_provider
        self._token = token
        self._interval = max(0.5, interval)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_run: datetime | None = None
        self.last_summary: dict[str, int] = {}
        self.last_error: str = ""

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="copier", daemon=True)
        self._thread.start()
        log.info("Copier loop started (every %.1fs)", self._interval)

    def stop(self) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=10)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                url = self._url_for()
                if url:
                    self.last_summary = run_once(url, self._token)
                    self.last_run = datetime.now(timezone.utc)
                    self.last_error = ""
            except Exception as exc:  # noqa: BLE001 - the loop must outlive any pass
                self.last_error = str(exc)
                log.exception("copier: pass failed")

            # Sleep the remainder of the interval, so a slow pass does not
            # stack up behind itself.
            elapsed = time.monotonic() - started
            self._stop.wait(max(0.2, self._interval - elapsed))
