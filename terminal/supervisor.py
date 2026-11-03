"""Run one account's MetaTrader terminal, inside its container.

The orchestrator starts one container per account and gives it only:

    TZ_ACCOUNT_ID   which account this terminal is for
    TZ_URL          TradeZulu's API, as reachable on the Docker network
    TZ_TOKEN        the ingest token -- the same one the Expert Advisor uses

The login, server and password are fetched from TradeZulu with that token, so
no password is ever in a container's environment or in `docker inspect`.

What this does, in order: bring up a virtual screen and a VNC server on it,
put the account's data on the /data volume, write the Expert Advisor's preset
and the start-up file, start MetaTrader, and then watch it -- the login, the
WebRequest permission, updates that want a restart, a terminal that exits --
writing what it sees to /data/status.json, which the orchestrator reads and
passes on to the web interface.

Success is never inferred from a click. The only evidence that the terminal
works is TradeZulu having heard from this account's Expert Advisor.
"""

from __future__ import annotations

import contextlib
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

DATA = Path("/data")
MT5 = Path("/opt/tz/mt5").resolve()
EA = Path("/opt/tz/ea")
ENV = dict(os.environ)
ACCOUNT_ID = int(os.environ["TZ_ACCOUNT_ID"])
API = os.environ["TZ_URL"].rstrip("/")
TOKEN = os.environ["TZ_TOKEN"]

#: Kept on the volume, so they survive the container being replaced by one on
#: a newer image: the saved login, history, and the Expert Advisor's files.
#: Everything else -- Wine, the binaries -- comes from the image every time.
PERSIST = ("Config", "Bases", "MQL5", "Profiles", "logs")

#: MetaTrader's algorithmic-trading switches. A fresh install's first login
#: counts as the account changing, and by default that turns trading off.
FLAGS = {"Enabled": "1", "Account": "0", "Profile": "0", "Chart": "0", "Api": "0"}

WEBREQUEST_ATTEMPTS = 3
STATUS: dict = {}


# --- small helpers ------------------------------------------------------------

def log(message: str) -> None:
    print(time.strftime("%H:%M:%S"), message, flush=True)


def status(**changes) -> None:
    STATUS.update(changes, at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    tmp = DATA / ".status.json"
    tmp.write_text(json.dumps(STATUS, indent=1))
    tmp.replace(DATA / "status.json")


def sh(*args: str, timeout: float | None = 30) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(list(args), env=ENV, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(list(args), 1, "", "timeout")


def background(*args: str, cwd: Path | None = None) -> subprocess.Popen:
    return subprocess.Popen(list(args), cwd=cwd, env=ENV,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def api(path: str) -> dict:
    request = urllib.request.Request(API + path, headers={"X-API-Key": TOKEN})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def plan_entry() -> tuple[dict | None, dict]:
    plan = api("/agent/terminals")
    for entry in plan.get("terminals", []):
        if int(entry.get("account_id", -1)) == ACCOUNT_ID:
            return entry, plan
    return None, plan


# --- the screen ---------------------------------------------------------------

def windows() -> dict[str, str]:
    ids = sh("xdotool", "search", "--name", ".").stdout.split()
    return {w: sh("xdotool", "getwindowname", w).stdout.strip() for w in ids}


def geometry(window: str) -> tuple[int, int, int, int] | None:
    """The client area, from xwininfo. Under a reparenting window manager
    xdotool reports positions offset by the frame, which puts every click a
    row too low -- into the Server field, once."""
    out = sh("xwininfo", "-id", window).stdout
    found = dict(re.findall(r"(Absolute upper-left X|Absolute upper-left Y|Width|Height):\s+(-?\d+)", out))
    try:
        return (int(found["Absolute upper-left X"]), int(found["Absolute upper-left Y"]),
                int(found["Width"]), int(found["Height"]))
    except KeyError:
        return None


def brightness(x: int, y: int, size: int = 7) -> float:
    out = sh("import", "-window", "root", "-crop", f"{size}x{size}+{x - size // 2}+{y - size // 2}",
             "-colorspace", "gray", "-format", "%[fx:mean]", "info:").stdout
    try:
        return float(out.strip())
    except ValueError:
        return 1.0


def screenshot(name: str) -> None:
    sh("import", "-window", "root", str(DATA / f"{name}.png"))


def main_window(login: str) -> str | None:
    return next((w for w, n in windows().items() if login and login in n), None)


def refusal_dialog() -> str | None:
    """MetaTrader's anti-debugger box: small, and titled after the program."""
    for window, name in windows().items():
        box = geometry(window)
        if name.lower().endswith(".exe") and box and box[2] < 400 and box[3] < 160:
            return name
    return None


def update_waiting() -> bool:
    return any("liveupdate" in n.lower() for n in windows().values())


# --- MetaTrader ---------------------------------------------------------------

def persist() -> None:
    """Put the account's own files on the volume and point the install at them."""
    for name in PERSIST:
        inside, kept = MT5 / name, DATA / name
        if inside.is_symlink():
            continue
        if not kept.exists():
            if inside.exists():
                shutil.copytree(inside, kept, symlinks=True)
            else:
                kept.mkdir(parents=True)
        shutil.rmtree(inside, ignore_errors=True)
        inside.symlink_to(kept)


def set_expert_flags(config: Path) -> None:
    """Set only these keys in [Experts] and leave the rest of it alone."""
    if not config.exists():
        config.write_text("[Experts]\r\n" + "".join(f"{k}={v}\r\n" for k, v in FLAGS.items()),
                          encoding="utf-16")
        return
    raw = config.read_bytes()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    out, seen, inside = [], set(), False
    for line in raw.decode(encoding).splitlines():
        text = line.strip()
        if text.startswith("["):
            if inside:
                out += [f"{k}={v}" for k, v in FLAGS.items() if k not in seen]
                seen.update(FLAGS)
            inside = text.lower() == "[experts]"
        elif inside and "=" in text and text.split("=", 1)[0].strip() in FLAGS:
            key = text.split("=", 1)[0].strip()
            seen.add(key)
            out.append(f"{key}={FLAGS[key]}")
            continue
        out.append(line)
    if inside:
        out += [f"{k}={v}" for k, v in FLAGS.items() if k not in seen]
    elif not seen:
        out += ["[Experts]"] + [f"{k}={v}" for k, v in FLAGS.items()]
    config.write_text("\r\n".join(out) + "\r\n", encoding=encoding)


def write_startup(entry: dict | None) -> None:
    """The start-up file. With an entry it carries the login, which MetaTrader
    only accepts from here; without one it is rewritten password-free, which
    is done as soon as the terminal has logged in and saved its own copy."""
    lines = ["[StartUp]", "Expert=TradeZuluCopier", "ExpertParameters=TradeZuluCopier.set",
             "Symbol=EURUSD", "Period=H1"]
    if entry:
        lines += ["", "[Common]", f"Login={entry['login']}", f"Password={entry['password']}",
                  f"Server={entry['server']}"]
    (MT5 / "tzstart.ini").write_text("\n".join(lines) + "\n", encoding="utf-8")


def prepare(entry: dict, callback: str) -> None:
    experts = MT5 / "MQL5/Experts"
    experts.mkdir(parents=True, exist_ok=True)
    # The image's build, every start: an image built for a newer MetaTrader
    # brings the .ex5 that matches it, and the volume must not keep an old one.
    for name in ("TradeZuluCopier.mq5", "TradeZuluCopier.ex5"):
        shutil.copy2(EA / name, experts / name)
    (MT5 / "Config").mkdir(exist_ok=True)
    set_expert_flags(MT5 / "Config/common.ini")
    presets = MT5 / "MQL5/Presets"
    presets.mkdir(parents=True, exist_ok=True)
    (presets / "TradeZuluCopier.set").write_text(
        f"ServerUrl={callback}\nApiKey={TOKEN}\nPollSeconds=3\n", encoding="utf-8")
    write_startup(entry)


def start() -> subprocess.Popen:
    log("starting MetaTrader")
    return background("wine", "terminal64.exe", "/portable", "/config:tzstart.ini", cwd=MT5)


def kill_wine() -> None:
    sh("wineserver", "-k")
    time.sleep(2)


def stop(proc: subprocess.Popen | None, login: str, grace: int = 40) -> None:
    """Close MetaTrader the way a person would, so it saves what it keeps."""
    window = main_window(login)
    if window:
        sh("xdotool", "windowactivate", window)
        time.sleep(0.5)
        sh("xdotool", "key", "--window", window, "alt+F4")
        deadline = time.time() + grace
        while time.time() < deadline and proc is not None and proc.poll() is None:
            time.sleep(1)
    kill_wine()


class TerminalLog:
    """MetaTrader's own log for today, read from where this run started."""

    def __init__(self) -> None:
        self.day = ""
        self.offset = 0

    def path(self) -> Path:
        return MT5 / "logs" / f"{time.strftime('%Y%m%d')}.log"

    def mark(self) -> None:
        self.day = time.strftime("%Y%m%d")
        try:
            self.offset = self.path().stat().st_size & ~1
        except OSError:
            self.offset = 0

    def text(self) -> str:
        if time.strftime("%Y%m%d") != self.day:  # a new day starts a new file
            self.day, self.offset = time.strftime("%Y%m%d"), 0
        try:
            with self.path().open("rb") as handle:
                handle.seek(self.offset)
                return handle.read().decode("utf-16le", "ignore").replace("\r", "")
        except OSError:
            return ""


def allow_webrequest(login: str, url: str) -> bool:
    """Add TradeZulu to the terminal's WebRequest list through its Options
    dialog, which is the only way in: MetaTrader keeps the list encrypted."""
    window = main_window(login)
    if not window:
        log("no terminal window yet")
        return False
    before = set(windows())
    sh("xdotool", "windowactivate", window)
    time.sleep(1.5)
    sh("xdotool", "key", "--window", window, "ctrl+o")
    dialog = None
    for _ in range(24):
        time.sleep(0.5)
        for candidate in set(windows()) - before:
            box = geometry(candidate)
            if box and box[2] > 200 and box[3] > 150:
                dialog = candidate
        if dialog:
            break
    if not dialog:
        log("the Options dialog did not open")
        return False
    left, top, width, height = geometry(dialog)

    def point(fx: float, fy: float) -> tuple[str, str]:
        return str(left + int(width * fx)), str(top + int(height * fy))

    def click(fx: float, fy: float, repeat: int = 1) -> None:
        sh("xdotool", "mousemove", *point(fx, fy), "click", "--repeat", str(repeat), "1")

    click(0.27, 0.041)                       # Experts tab
    time.sleep(1)
    x, y = point(0.056, 0.535)               # "Allow WebRequest for listed URL"
    if brightness(int(x), int(y)) > 0.85:    # an unticked box is white inside
        click(0.056, 0.535)
        time.sleep(0.7)
    click(0.27, 0.609, repeat=2)             # the "add new URL" row
    time.sleep(1.5)
    sh("xdotool", "type", "--delay", "50", url)
    time.sleep(0.5)
    sh("xdotool", "key", "Return")
    time.sleep(1)
    screenshot("webrequest")
    click(0.66, 0.95)                        # OK
    time.sleep(2)
    if dialog in windows():
        log("the Options dialog did not close; the entry was probably not saved")
        sh("xdotool", "key", "--window", dialog, "Escape")
        return False
    log(f"entered {url} in the WebRequest list")
    return True


def heard_from(entry: dict | None, since: float) -> bool:
    seen = (entry or {}).get("last_seen")
    if not seen:
        return False
    at = datetime.fromisoformat(seen).timestamp()
    # Since this run started, and recently: the Expert Advisor polls every few
    # seconds, so a minute and a half of silence is a terminal that stopped.
    return at >= since - 5 and time.time() - at < 90


# --- the loop -----------------------------------------------------------------

def main() -> None:
    # A restarted container keeps its filesystem; a stale X lock or Wine server
    # socket from the last run makes every launch quit at once. (/tmp is a
    # tmpfs when started by the orchestrator, so this is belt and braces.)
    for stale in ["/tmp/.X1-lock", "/tmp/.X11-unix/X1", *glob.glob("/tmp/.wine-*")]:
        if os.path.isdir(stale):
            shutil.rmtree(stale, ignore_errors=True)
        elif os.path.lexists(stale):
            os.unlink(stale)

    with contextlib.suppress(OSError, ValueError):
        STATUS.update(json.loads((DATA / "status.json").read_text()))
    STATUS.pop("fatal", None)
    build = (Path("/opt/tz/mt5-build").read_text().strip()
             if Path("/opt/tz/mt5-build").exists() else "")
    status(phase="starting", message="Starting the virtual screen.", build=build)

    background("Xvfb", ":1", "-ac", "-screen", "0", "1400x1000x24")
    time.sleep(2)
    background("openbox")
    background("x11vnc", "-display", ":1", "-rfbport", "5900", "-shared", "-forever",
               "-nopw", "-quiet", "-noxdamage")

    entry = None
    while entry is None:
        try:
            entry, plan = plan_entry()
        except Exception as error:  # noqa: BLE001 - the app may still be starting
            status(phase="starting", message=f"Waiting for TradeZulu: {error}")
            time.sleep(10)
            continue
        if entry is None:
            status(phase="starting", message="TradeZulu has no credentials for this account yet.")
            time.sleep(15)
    login = str(entry["login"])
    callback = plan["callback_url"]
    allow_url = callback[: -len("/api")] if callback.endswith("/api") else callback

    persist()
    prepare(entry, callback)
    terminal_log = TerminalLog()
    terminal_log.mark()
    proc = start()
    holder = {"proc": proc}

    def on_term(*_):
        log("stopping")
        stop(holder["proc"], login)
        status(phase="stopped", message="The container was stopped.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, on_term)

    started = time.time()
    authorized = False
    refused = ""
    reported = False
    tries, last_try, restarts, update_restarts = 0, 0.0, 0, 0
    status(phase="starting", message="MetaTrader is starting.", login=login, attempts=0)

    while True:
        time.sleep(5)

        name = refusal_dialog()
        if name:
            screenshot("refused")
            status(phase="failed", fatal=True,
                   message=f"{name} was refused by MetaTrader's anti-debugger check on this "
                           "Wine build. Build this broker's image on another Wine version.")
            log(STATUS["message"])
            kill_wine()
            while True:  # keep the screen up for whoever looks; the orchestrator reports it
                time.sleep(3600)

        text = terminal_log.text()
        if not authorized:
            if re.search(rf"'{re.escape(login)}': authorized on", text):
                authorized, refused = True, ""
                log("logged in")
                write_startup(None)  # MetaTrader has its own copy of the password now
            else:
                failure = re.findall(rf"'{re.escape(login)}': authorization on .*? failed \(([^)]*)\)", text)
                if failure and failure[-1] != refused:
                    refused = failure[-1]
                    log(f"login refused: {refused}")
                    status(phase="failed", message=f"The broker refused the login: {refused}. "
                           "Check the account number, password and server.")

        if update_waiting() and update_restarts < 3:
            update_restarts += 1
            log("an update is waiting; restarting MetaTrader to install it")
            stop(proc, login)
            write_startup(None if authorized else entry)
            terminal_log.mark()
            proc = holder["proc"] = start()
            started, authorized, reported = time.time(), False, False
            continue

        try:
            entry_now, _ = plan_entry()
        except Exception:  # noqa: BLE001
            entry_now = entry
        ok = heard_from(entry_now, started)

        if ok and not reported:
            reported = True
            log("the Expert Advisor is reporting to TradeZulu")
            status(reported_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        if ok:
            status(phase="running", message="", attempts=tries)
        elif reported:
            status(phase="quiet", message="The Expert Advisor was reporting and has stopped.")
        elif authorized:
            if tries < WEBREQUEST_ATTEMPTS and time.time() - started > 20 and time.time() - last_try > 60:
                tries += 1
                last_try = time.time()
                log(f"no report yet; granting WebRequest (attempt {tries})")
                status(phase="retrying", attempts=tries,
                       message="Allowing TradeZulu in MetaTrader's WebRequest list.")
                allow_webrequest(login, allow_url)
            elif tries >= WEBREQUEST_ATTEMPTS and time.time() - last_try > 120:
                status(phase="failed", attempts=tries,
                       message="Logged in, but the Expert Advisor never reached TradeZulu. "
                               "Check Tools -> Options -> Expert Advisors on its screen.")
        elif not refused:
            status(phase="starting", message="MetaTrader is starting and logging in.")

        if proc.poll() is not None:
            restarts += 1
            log(f"MetaTrader exited; starting it again ({restarts})")
            time.sleep(min(60, 5 * restarts))
            write_startup(None if authorized else entry)
            terminal_log.mark()
            proc = holder["proc"] = start()
            started, authorized, reported = time.time(), False, False


if __name__ == "__main__":
    main()
