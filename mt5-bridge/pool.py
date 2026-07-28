"""A worker process per account, and the routing in front of them.

Each account gets its own terminal, its own data directory and its own
interpreter running :mod:`worker`. This module starts them, talks to them, and
restarts the ones that stop answering.

Two properties are worth stating because the rest of the bridge relies on
them:

* **One request at a time per worker.** Each worker holds a lock, so a slow
  order on one account cannot interleave with a read on the same account. It
  does not block *other* accounts, which is the point of separate processes.
* **A dead worker is not fatal.** Workers are restarted on demand, and a
  request that arrives while one is being replaced fails with a plain message
  rather than hanging. Copying to five accounts continues when the sixth
  broker's terminal falls over.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

WORKER_SCRIPT = os.getenv("WORKER_SCRIPT", r"Z:\opt\bridge\worker.py")
PYTHON = os.getenv("WINE_PYTHON_WIN", r"C:\python\python.exe")
DATA_ROOT = os.getenv("MT5_ACCOUNT_ROOT", r"C:\accounts")
# A single request should never hang the whole bridge. The bound is generous
# because the *first* call for a new account copies the terminal directory
# before it can connect; every call after that is fast.
REQUEST_TIMEOUT = float(os.getenv("WORKER_TIMEOUT", "240"))


class WorkerError(RuntimeError):
    pass


class AccountWorker:
    """One subprocess, one terminal, one account."""

    def __init__(self, account_id: str, config: dict[str, Any]) -> None:
        self.account_id = account_id
        self.config = config
        self.process: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()
        self.last_error = ""
        self.started_at = 0.0

    # -- lifecycle -------------------------------------------------------
    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        if self.alive:
            return

        # The supervisor is itself a Windows process under Wine, so Windows
        # paths are the native ones here -- no translation needed.
        data_path = f"{DATA_ROOT}\\{self.account_id}"
        Path(data_path).mkdir(parents=True, exist_ok=True)

        payload = dict(self.config)
        payload["data_path"] = data_path

        environment = dict(os.environ)
        environment["WORKER_ACCOUNT"] = json.dumps(payload)
        # Each terminal keeps its own state under its own directory.
        environment["MT5_DATA_PATH"] = data_path

        # Not "wine python.exe": this code is already running under Wine as a
        # Windows process, so it launches the worker the way Windows would.
        self.process = subprocess.Popen(  # noqa: S603 - fixed argv, no shell
            [PYTHON, WORKER_SCRIPT],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=environment,
        )
        self.started_at = time.time()
        self.last_error = ""

    def stop(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        try:
            process.stdin.close()  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001 - it is going away regardless
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    def restart(self) -> None:
        self.stop()
        self.start()

    # -- requests --------------------------------------------------------
    def call(self, command: str, **args: Any) -> Any:
        with self.lock:
            if not self.alive:
                self.start()
            if self.process is None or self.process.stdin is None:
                raise WorkerError(f"account {self.account_id} has no worker running")

            request = json.dumps({"command": command, "args": args})
            try:
                self.process.stdin.write(request + "\n")
                self.process.stdin.flush()
            except (BrokenPipeError, ValueError) as exc:
                self.restart()
                raise WorkerError(f"the worker for {self.account_id} died: {exc}") from exc

            line = _read_line(self.process, REQUEST_TIMEOUT)
            if line is None:
                # A worker that stopped answering is not going to recover by
                # itself, and leaving it wedged would block every later call.
                self.restart()
                raise WorkerError(
                    f"account {self.account_id} did not answer within {REQUEST_TIMEOUT:g}s"
                )

        try:
            reply = json.loads(line)
        except json.JSONDecodeError as exc:
            raise WorkerError(f"unreadable reply from {self.account_id}: {line[:120]}") from exc

        if not reply.get("ok"):
            self.last_error = str(reply.get("error", "unknown error"))
            raise WorkerError(self.last_error)
        return reply.get("result")

    def describe(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "login": self.config.get("login", ""),
            "server": self.config.get("server", ""),
            "alive": self.alive,
            "uptime_seconds": int(time.time() - self.started_at) if self.alive else 0,
            "last_error": self.last_error,
        }


def _read_line(process: subprocess.Popen[str], timeout: float) -> str | None:
    """Read one line, giving up after *timeout* seconds.

    readline() on a pipe has no timeout of its own, so it is run on a thread
    that is allowed to be abandoned. The worker is restarted when that
    happens, so nothing is left reading into a pipe nobody owns.
    """
    result: list[str] = []

    def reader() -> None:
        try:
            line = process.stdout.readline()  # type: ignore[union-attr]
            if line:
                result.append(line)
        except Exception:  # noqa: BLE001 - the caller treats silence as failure
            pass

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(timeout)
    return result[0] if result else None


class WorkerPool:
    """Every account's worker, keyed by account id."""

    def __init__(self) -> None:
        self._workers: dict[str, AccountWorker] = {}
        self._lock = threading.Lock()

    def configure(self, accounts: list[dict[str, Any]]) -> dict[str, Any]:
        """Replace the set of accounts, keeping workers that have not changed.

        Restarting a terminal costs seconds and drops its connection, so an
        account whose credentials are unchanged keeps the worker it has.
        """
        wanted = {str(account["id"]): account for account in accounts}

        with self._lock:
            for account_id in list(self._workers):
                if account_id not in wanted:
                    self._workers.pop(account_id).stop()

            for account_id, config in wanted.items():
                existing = self._workers.get(account_id)
                if existing is None:
                    self._workers[account_id] = AccountWorker(account_id, config)
                elif _credentials_changed(existing.config, config):
                    existing.config = config
                    existing.restart()
                else:
                    existing.config = config

        return {"accounts": sorted(wanted)}

    def get(self, account_id: str) -> AccountWorker:
        with self._lock:
            worker = self._workers.get(str(account_id))
        if worker is None:
            raise WorkerError(f"account {account_id} is not configured on the bridge")
        return worker

    def describe(self) -> list[dict[str, Any]]:
        with self._lock:
            return [worker.describe() for worker in self._workers.values()]

    def shutdown(self) -> None:
        with self._lock:
            for worker in self._workers.values():
                worker.stop()
            self._workers.clear()


def _credentials_changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
    return any(
        str(before.get(field, "")) != str(after.get(field, ""))
        for field in ("login", "server", "password")
    )
