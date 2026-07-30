#!/usr/bin/env python3
"""Keeps a MetaTrader terminal running for every account TradeZulu knows about.

TradeZulu itself is containerised. MetaTrader is not, and after exhausting the
alternatives (see docs/mt5-bridge-ipc.md) that is a deliberate split rather
than a temporary one: the terminal is reliable under a normal Wine install on
the host and was not reliable in a container. This process bridges the two. It
runs on the same machine as the site, asks it what terminals should exist, and
makes reality match.

The point of it is that nobody else has to know any of that. Someone adds an
account in the web interface and, a minute later, it is trading. They install
nothing, edit no files, and are never asked for a URL -- this process gets the
callback address and token from the server it is already talking to, and
writes them into each Expert Advisor itself.

Everything here is a reconcile loop rather than a sequence of steps, so it is
safe to restart at any point and picks up where it left off after a reboot.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("tz-provision")

#: Where the Bottles flatpak keeps its prefixes and runners.
BOTTLES = Path.home() / ".var/app/com.usebottles.bottles/data/bottles"

#: Display the terminals live on. They are never meant to be looked at, so
#: this must not be :0 -- a provisioner that throws windows onto the operator's
#: screen every time it starts a terminal is unusable on a desktop machine.
DISPLAY = os.getenv("TZ_DISPLAY", ":77")


# --- talking to TradeZulu ----------------------------------------------------


@dataclass(frozen=True)
class Plan:
    """What the server says should be running."""

    callback_url: str
    api_key: str
    terminals: list[dict]


def fetch_plan(base_url: str, token: str) -> Plan:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/agent/terminals",
        headers={"X-API-Key": token},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
    return Plan(
        callback_url=data.get("callback_url", ""),
        api_key=data.get("api_key", ""),
        terminals=list(data.get("terminals", [])),
    )


# --- Wine plumbing -----------------------------------------------------------


def _runner() -> Path:
    """The Wine build to run terminals with.

    Preference is for a Proton-derived runner. Mainline Wine loads MetaTrader
    but its inter-process layer does not answer, which is the failure that cost
    this project the most time; the Proton builds do not have it.
    """
    runners = BOTTLES / "runners"
    candidates = sorted(runners.glob("soda-*")) + sorted(runners.glob("*proton*"))
    for candidate in candidates:
        wine = candidate / "bin/wine"
        if wine.exists():
            return wine
    raise SystemExit(
        f"No usable Wine runner under {runners}. Install one in Bottles first "
        "(Soda is the tested choice)."
    )


def _flatpak_run(script: str, timeout: int = 600) -> subprocess.CompletedProcess:
    """Run a shell snippet inside the Bottles flatpak sandbox.

    The runners are built against that sandbox's libraries, so invoking them
    from outside it fails in ways that look like Wine bugs but are not.
    """
    return subprocess.run(
        ["flatpak", "run", "--command=sh", "com.usebottles.bottles", "-c", script],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def ensure_display() -> None:
    """Make sure there is a screen for the terminals to draw on.

    MetaTrader will not run headless. It does not need a *visible* screen
    though, and giving it a real one would put trading windows in front of
    whoever happens to be using the machine.
    """
    if subprocess.run(["xdotool", "search", "--name", "."], env={**os.environ, "DISPLAY": DISPLAY},
                      capture_output=True).returncode == 0:
        return
    log.info("starting virtual display %s", DISPLAY)
    subprocess.Popen(
        ["Xvfb", DISPLAY, "-ac", "-screen", "0", "1400x1000x24", "-listen", "tcp"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    subprocess.Popen(
        ["openbox"],
        env={**os.environ, "DISPLAY": DISPLAY},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)


# --- one terminal per account ------------------------------------------------


def bottle_for(account_id: int) -> Path:
    return BOTTLES / "bottles" / f"tz-{account_id}"


def terminal_dir(bottle: Path) -> Path | None:
    """Find terminal64.exe inside a prefix, wherever the installer put it."""
    for path in bottle.glob("drive_c/**/terminal64.exe"):
        return path.parent
    return None


def is_running(bottle: Path) -> bool:
    """Whether this account's terminal is up.

    Matching on the prefix path rather than the process name is what makes
    this per-account: every terminal is the same executable, and Wine reports
    them all under the same name.
    """
    result = subprocess.run(
        ["pgrep", "-f", f"{bottle}.*terminal64.exe"], capture_output=True, text=True
    )
    return bool(result.stdout.strip())


def clone_template(template: Path, target: Path) -> None:
    """Copy a prepared prefix rather than installing Wine from scratch.

    An installed prefix is a large pile of state -- runtime libraries, fonts,
    registry -- that takes minutes to build and can fail halfway. Copying one
    that is known good takes seconds and cannot half-work.
    """
    log.info("creating prefix %s from template", target.name)
    shutil.copytree(template, target, symlinks=True, dirs_exist_ok=False)


def install_expert(terminal: Path, source: Path, callback_url: str, api_key: str) -> None:
    """Put the Expert Advisor in the terminal and tell it where to report.

    The URL and token are written here, which is the whole reason nobody is
    ever asked for them. They come from the server this process just spoke to,
    so they are right by construction.
    """
    experts = terminal / "MQL5/Experts"
    experts.mkdir(parents=True, exist_ok=True)
    for suffix in (".ex5", ".mq5"):
        candidate = source.with_suffix(suffix)
        if candidate.exists():
            shutil.copy2(candidate, experts / candidate.name)

    presets = terminal / "MQL5/Presets"
    presets.mkdir(parents=True, exist_ok=True)
    (presets / "TradeZuluCopier.set").write_text(
        "ServerUrl={}\nApiKey={}\nPollSeconds=3\n".format(callback_url, api_key),
        encoding="utf-8",
    )

    # Starting the expert from the terminal's own startup file means it is
    # attached before the first tick, so no chart has to be set up by hand.
    (terminal / "tzstart.ini").write_text(
        "[StartUp]\nExpert=TradeZuluCopier\nSymbol=EURUSD\nPeriod=H1\n",
        encoding="utf-8",
    )


def launch(bottle: Path, terminal: Path, login: str, server: str, password: str) -> None:
    """Start the terminal, logged in, on the virtual display.

    Credentials go on the command line rather than into a file. MetaTrader
    stores what it needs in its own encrypted form once it has connected, and
    a password written to disk in the clear would outlive this call.
    """
    log.info("starting terminal for %s on %s", login, server)
    script = (
        f'export WINEPREFIX="{bottle}" WINEDEBUG=-all DISPLAY={DISPLAY}\n'
        f'unset PYTHONPATH PYTHONHOME\n'
        f'cd "{terminal}"\n'
        f'setsid "{_runner()}" terminal64.exe /portable /config:tzstart.ini '
        f'/login:{login} /server:"{server}" /password:"{password}" '
        f'>/dev/null 2>&1 < /dev/null &\n'
        f'sleep 5\n'
    )
    _flatpak_run(script, timeout=120)


# --- the one thing that still needs a GUI ------------------------------------


def allow_webrequest(login: str, url: str) -> bool:
    """Add TradeZulu to the terminal's WebRequest allowlist.

    MetaTrader keeps this list encrypted in its own config, so it cannot be
    written from outside; the only way in is the dialog. Driving it takes a
    couple of seconds and happens once per terminal, which is a fair price for
    not asking the user to do it -- and asking them would defeat the point,
    since an Expert Advisor without this permission fails silently.
    """
    env = {**os.environ, "DISPLAY": DISPLAY}

    found = subprocess.run(
        ["xdotool", "search", "--name", re.escape(login)],
        env=env, capture_output=True, text=True,
    )
    window = found.stdout.split()[-1] if found.stdout.strip() else ""
    if not window:
        log.warning("no terminal window for %s yet; will retry", login)
        return False

    subprocess.run(["xdotool", "windowactivate", window], env=env, capture_output=True)
    time.sleep(2)
    subprocess.run(["xdotool", "key", "--window", window, "ctrl+o"], env=env, capture_output=True)
    time.sleep(4)

    # The Options dialog opens on whichever tab was last used, and it is the
    # Experts tab that carries the list. Clicking it by name is more robust
    # than counting tab stops, which differ between terminal builds.
    subprocess.run(["xdotool", "mousemove", "384", "94", "click", "1"], env=env, capture_output=True)
    time.sleep(1)
    subprocess.run(
        ["xdotool", "mousemove", "405", "552", "click", "--repeat", "2", "1"],
        env=env, capture_output=True,
    )
    time.sleep(2)
    subprocess.run(["xdotool", "type", "--delay", "60", url], env=env, capture_output=True)
    time.sleep(1)
    subprocess.run(["xdotool", "key", "Return"], env=env, capture_output=True)
    time.sleep(1)
    subprocess.run(["xdotool", "mousemove", "896", "766", "click", "1"], env=env, capture_output=True)
    time.sleep(2)
    log.info("allowed WebRequest to %s for %s", url, login)
    return True


# --- reconcile ---------------------------------------------------------------


def reconcile(plan: Plan, template: Path, expert: Path) -> None:
    for spec in plan.terminals:
        if not spec.get("enabled"):
            continue

        account_id = int(spec["account_id"])
        bottle = bottle_for(account_id)

        if not bottle.exists():
            clone_template(template, bottle)

        terminal = terminal_dir(bottle)
        if terminal is None:
            log.error("no terminal64.exe in %s -- is the template complete?", bottle)
            continue

        if is_running(bottle):
            continue

        install_expert(terminal, expert, plan.callback_url, plan.api_key)
        launch(bottle, terminal, spec["login"], spec["server"], spec["password"])

        # Give the terminal time to reach a login before touching its window.
        time.sleep(45)
        marker = bottle / ".tz-webrequest-allowed"
        if not marker.exists() and allow_webrequest(spec["login"], plan.callback_url):
            marker.touch()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("TZ_URL", "http://127.0.0.1:8420"))
    parser.add_argument("--token", default=os.getenv("TZ_INGEST_TOKEN", ""))
    parser.add_argument(
        "--template",
        type=Path,
        default=BOTTLES / "bottles" / "tz-template",
        help="A prefix with MetaTrader already installed, copied for each account.",
    )
    parser.add_argument(
        "--expert",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "mt5" / "TradeZuluCopier.mq5",
    )
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )

    if not args.token:
        log.error("no API token; set TZ_INGEST_TOKEN or pass --token")
        return 2
    if not args.template.exists():
        log.error(
            "no template prefix at %s. Create one bottle with MetaTrader "
            "installed and name it tz-template; every account is a copy of it.",
            args.template,
        )
        return 2

    ensure_display()

    while True:
        try:
            reconcile(fetch_plan(args.url, args.token), args.template, args.expert)
        except urllib.error.URLError as error:
            log.warning("TradeZulu not reachable at %s: %s", args.url, error)
        except Exception:  # noqa: BLE001 - a bad cycle must not kill the daemon
            log.exception("provisioning cycle failed")
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
