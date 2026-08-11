#!/usr/bin/env python3
"""Keeps a MetaTrader terminal running for every account TradeZulu knows about.

TradeZulu itself is containerised. MetaTrader is not, and after exhausting the
alternatives (see docs/metatrader.md) that is a deliberate split rather
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
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("tz-provision")

#: Where the Bottles flatpak keeps its prefixes and runners.
BOTTLES = Path.home() / ".var/app/com.usebottles.bottles/data/bottles"

#: Display the terminals live on. They are never meant to be looked at, so
#: this must not be :0 -- a provisioner that throws windows onto the operator's
#: screen every time it starts a terminal is unusable on a desktop machine.
#:
#: This is the *base*: each account gets its own display at this number plus
#: its account id, so no two accounts ever draw on the same screen. One screen
#: for all of them worked while nobody looked at it, but the moment a terminal
#: can be watched from the web interface it becomes a privacy boundary --
#: whoever may see account 3 must not be shown account 4's open positions
#: because the two windows happen to be stacked in the same place.
DISPLAY = os.getenv("TZ_DISPLAY", ":77")

#: VNC ports follow the display number: display :78 is served on 5978. One
#: server per display, so a viewer is connected to exactly one account.
VNC_PORT_BASE = int(os.getenv("TZ_VNC_PORT_BASE", "5900"))


def display_for(account_id: int) -> str:
    """The display this account's terminal draws on, and nobody else's.

    Only a display we start ourselves can be multiplied like this. One written
    ``host:N`` belongs to somewhere else -- another machine, or a container --
    and there is no second screen to be had there, so every terminal shares it
    and the isolation below is not available. Said once, at startup, rather
    than pretended.
    """
    if not DISPLAY.startswith(":"):
        return DISPLAY
    base = int(DISPLAY[1:].split(".")[0])
    return f":{base + int(account_id)}"


def vnc_port_for(display: str) -> int | None:
    """The port this display is served on, or None if it is not ours to serve."""
    if not display.startswith(":"):
        return None
    return VNC_PORT_BASE + int(display[1:].split(".")[0])


# --- talking to TradeZulu ----------------------------------------------------


@dataclass(frozen=True)
class Plan:
    """What the server says should be running."""

    callback_url: str
    api_key: str
    terminals: list[dict]
    #: When the weekly restart should happen, as the server has it. Kept with
    #: the plan so the window can be changed in the web interface rather than
    #: by editing a unit file on the machine.
    maintenance: dict
    #: Where this plan came from, and what it took to ask -- so anything that
    #: has a plan can also report back without being handed them separately.
    base_url: str = ""
    token: str = ""
    #: The address to serve each terminal's screen on, as TradeZulu reported
    #: it: the host end of the bridge its own container sits on. Empty means
    #: the site cannot reach a VNC server here, and none is started.
    vnc_bind: str = ""
    #: Every account the server has, including ones with no credentials yet.
    #: Anything on this machine that is not in here belongs to an account that
    #: has been forgotten, and is cleared up. None means the server did not say
    #: -- an older one -- and then nothing is ever removed on a guess.
    known_accounts: set[int] | None = None


def fetch_plan(base_url: str, token: str) -> Plan:
    request = urllib.request.Request(
        base_url.rstrip("/") + "/api/agent/terminals",
        headers={"X-API-Key": token},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
    known = data.get("known_accounts")
    return Plan(
        callback_url=data.get("callback_url", ""),
        api_key=data.get("api_key", ""),
        terminals=list(data.get("terminals", [])),
        maintenance=dict(data.get("maintenance") or {}),
        vnc_bind=str(data.get("vnc_bind") or ""),
        base_url=base_url,
        token=token,
        known_accounts={int(value) for value in known} if known is not None else None,
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


def _flatpak_argv(script: str) -> list[str]:
    """Run a shell snippet inside the Bottles flatpak sandbox.

    The runners are built against that sandbox's libraries, so invoking them
    from outside it fails in ways that look like Wine bugs but are not.
    """
    return ["flatpak", "run", "--command=sh", "com.usebottles.bottles", "-c", script]


def _flatpak_spawn(script: str) -> None:
    """Start something in the sandbox and leave it running.

    ``flatpak run`` does not return while anything is still alive inside its
    sandbox, and a terminal is meant to stay alive for days. Waiting for it
    would hang the provisioner on the first account it started.
    """
    subprocess.Popen(
        _flatpak_argv(script),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )


def ensure_display(display: str = "", required: bool = True) -> bool:
    """Make sure there is a screen for a terminal to draw on.

    MetaTrader will not run headless. It does not need a *visible* screen
    though, and giving it a real one would put trading windows in front of
    whoever happens to be using the machine.

    A display written ``host:N`` belongs to somewhere else -- another machine,
    or a container -- so it is used as given and never started here. Only a
    plain ``:N`` is ours to bring up, and the socket says whether it already
    is without needing an X client installed to ask.
    """
    display = display or DISPLAY
    if not display.startswith(":"):
        log.info("using the display at %s", display)
        return True

    if Path(f"/tmp/.X11-unix/X{display[1:]}").exists():
        return True

    if shutil.which("Xvfb") is None:
        message = (
            f"No display at {display} and Xvfb is not installed. "
            "Run install.sh, or apt install xvfb xdotool openbox."
        )
        # Fatal at startup, where it means nothing can run and saying so once
        # is kinder than failing account by account. Not fatal per account:
        # one screen that cannot be brought up is one terminal that does not
        # start, and the others have no part in it.
        if required:
            raise SystemExit(message)
        log.error("%s", message)
        return False

    log.info("starting virtual display %s", display)
    subprocess.Popen(
        ["Xvfb", display, "-ac", "-screen", "0", "1400x1000x24"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    if shutil.which("openbox"):
        subprocess.Popen(
            ["openbox"],
            env={**os.environ, "DISPLAY": display},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)
    return True


def ensure_vnc(display: str, bind: str) -> int | None:
    """Serve one display over VNC, for the web interface to show.

    One server per display, which is what makes this safe to put on a web page
    at all: a viewer is connected to a single account's screen and there is no
    window on it belonging to anybody else.

    Bound to the address TradeZulu itself reported -- the host end of the
    bridge its container sits on -- so the site can reach it and the network
    the machine is on cannot. Never 0.0.0.0: these are logged-in trading
    terminals, and x11vnc's own authentication is not worth relying on.
    """
    port = vnc_port_for(display)
    if port is None or not bind:
        return None

    if shutil.which("x11vnc") is None:
        log.warning(
            "x11vnc is not installed, so %s cannot be watched from the web "
            "interface. apt install x11vnc",
            display,
        )
        return None

    if _vnc_running(port):
        return port

    log.info("serving %s on %s:%s", display, bind, port)
    subprocess.Popen(
        [
            "x11vnc",
            "-display", display,
            "-listen", bind,
            "-rfbport", str(port),
            # -viewonly for now: this is for looking at a terminal that has gone
            # wrong, and a stray click on a live account is a placed order.
            "-viewonly",
            "-shared", "-forever", "-nopw", "-quiet",
            # Without this it exits the moment the display it was started for
            # blinks, and nothing would bring it back until the next cycle.
            "-loop",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return port


def _vnc_running(port: int) -> bool:
    """Is there already an x11vnc on this port?

    By its command line rather than by connecting: opening a socket to a VNC
    server counts as a client, and x11vnc logs and reference-counts those.
    """
    try:
        out = subprocess.run(
            ["pgrep", "-af", "x11vnc"], capture_output=True, text=True, timeout=5
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(f"-rfbport {port} " in f"{line} " for line in out.splitlines())


# --- one terminal per account ------------------------------------------------


def bottle_for(account_id: int) -> Path:
    return BOTTLES / "bottles" / f"tz-{account_id}"


def account_of(prefix: Path) -> int | None:
    """The account a prefix belongs to, or None if it is not one of ours.

    Templates are named ``tz-template-<broker>`` and are shared, so they are
    never anybody's -- which is what keeps the reaping below from deleting the
    thing every account is copied from.
    """
    match = re.fullmatch(r"tz-(\d+)", prefix.name)
    return int(match.group(1)) if match else None


# --- what we know about each account's terminal -------------------------------
#
# Kept beside the prefixes rather than inside them, because the most useful
# thing to do with a terminal that will not work is to delete its prefix and
# build a fresh one -- and bookkeeping that is deleted along with the thing it
# is counting cannot count past one. Every retry ladder here used to live in
# the prefix, so "rebuild and try again" would have looped for ever.

STATE_DIR = BOTTLES / ".tz-state"


def load_state(account_id: int) -> dict:
    path = STATE_DIR / f"{account_id}.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(account_id: int, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with suppress(OSError):
        (STATE_DIR / f"{account_id}.json").write_text(json.dumps(state, indent=1))


def forget_state(account_id: int) -> None:
    with suppress(OSError):
        (STATE_DIR / f"{account_id}.json").unlink()


def load_brokers() -> dict[str, dict]:
    path = Path(__file__).resolve().parent / "brokers.json"
    try:
        return {
            key: value
            for key, value in json.loads(path.read_text()).items()
            if isinstance(value, dict) and not key.startswith("_")
        }
    except (OSError, ValueError):
        log.warning("could not read %s; every account gets the generic terminal", path)
        return {}


def template_for(broker: str, server: str, fallback: Path) -> Path:
    """The prepared prefix to copy for this account.

    A broker-specific build ships that broker's server list, and without it
    the terminal cannot resolve a name like ``VantageMarkets-Live`` at all --
    it offers to open a new account instead, which looks like a rejected
    password. So picking the right template is not an optimisation.

    The server name is what decides, because it is the one field that always
    arrives correct: it comes from the broker. The broker *name* is whatever
    the terminal happened to report, which for a demo account can be
    something as unhelpful as "Demo Broker".
    """
    haystack = f"{broker} {server}".lower()
    for key, entry in load_brokers().items():
        needles = [str(m).lower() for m in entry.get("matches", []) if m]
        if not any(needle in haystack for needle in needles):
            continue
        candidate = BOTTLES / "bottles" / f"tz-template-{key}"
        if (candidate / ".tz-template-ready").exists():
            log.info("using the %s terminal for %s", key, server)
            return candidate
        log.warning(
            "%s looks like a %s account but no %s template is built "
            "(agent/make-template.sh %s); falling back to the generic terminal",
            server, key, key, key,
        )
    return fallback


def terminal_dir(bottle: Path) -> Path | None:
    """Find terminal64.exe inside a prefix, wherever the installer put it."""
    for path in bottle.glob("drive_c/**/terminal64.exe"):
        return path.parent
    return None


def _procs() -> list[tuple[int, bytes, bytes]]:
    """Every process we can read, as (pid, command line, environment)."""
    found: list[tuple[int, bytes, bytes]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (entry / "cmdline").read_bytes()
            environ = (entry / "environ").read_bytes()
        except OSError:
            continue  # the process ended, or is not ours to look at
        found.append((int(entry.name), command, environ))
    return found


def is_terminal(command: bytes, environ: bytes, bottle: Path) -> bool:
    """Whether this process is *the* MetaTrader terminal for one prefix.

    Wine reports a terminal under its *Windows* path -- every account's shows
    up as ``C:\\Program Files\\MetaTrader 5\\terminal64.exe`` -- so matching
    the command line cannot tell two accounts apart, and matching the Linux
    prefix path finds nothing at all. WINEPREFIX in the environment can: it is
    set per process and says exactly which account a terminal belongs to.

    The first word has to be the terminal itself. Wine starts it through a stub
    -- ``start.exe /exec terminal64.exe`` -- which names the terminal in its own
    command line and shares its environment, and that stub can outlive a launch
    that failed. Counting it meant a prefix with no terminal at all looked
    occupied for as long as the stub sat there, so nothing was ever restarted:
    exactly the terminal that is "stuck" and stays stuck.
    """
    if f"WINEPREFIX={bottle}".encode() not in environ.split(b"\0"):
        return False
    argv0 = command.split(b"\0")[0].lower().replace(b"\\", b"/")
    return argv0.rsplit(b"/", 1)[-1] == b"terminal64.exe"


def running_pids(bottle: Path) -> list[int]:
    """The terminal processes belonging to one account's prefix.

    Getting this wrong is not cosmetic in either direction: a check that fails
    to see a running terminal starts a second one on the same account, and two
    terminals copying the same master both place the order.
    """
    return [pid for pid, cmd, env in _procs() if is_terminal(cmd, env, bottle)]


def is_running(bottle: Path) -> bool:
    return bool(running_pids(bottle))


def stray_pids(bottle: Path) -> list[int]:
    """Everything else still attached to a prefix: sandboxes, stubs, wineserver.

    A launch goes through ``flatpak run``, which is a chain of bwrap sandboxes
    wrapping a shell, and if the terminal inside never comes up that chain is
    left behind holding the prefix. They accumulate one per attempt -- six of
    them were sitting on this project's own machine, from starts that failed
    days apart -- and a stale wineserver among them is enough to stop the next
    launch dead, because Wine attaches to the one already serving that prefix
    rather than starting the terminal.

    The wrappers do not have WINEPREFIX in their environment; it is exported
    by the script they are running, so it is in their command line instead.
    Both shapes are matched, quoted exactly, so ``tz-1`` never catches
    ``tz-11``.
    """
    want_env = f"WINEPREFIX={bottle}".encode()
    want_arg = f'WINEPREFIX="{bottle}"'.encode()
    mine = os.getpid()
    pids: list[int] = []
    for pid, command, environ in _procs():
        if pid == mine or is_terminal(command, environ, bottle):
            continue
        if want_env in environ.split(b"\0") or want_arg in command:
            pids.append(pid)
    return pids


def _signal(pids: list[int], sig: int) -> None:
    for pid in pids:
        with suppress(OSError):
            os.kill(pid, sig)


def stop_terminal(bottle: Path, timeout: float = 40.0) -> None:
    """Stop an account's terminal, giving it time to save.

    MetaTrader writes its settings only when it exits cleanly. Killing it
    outright silently loses them -- including the WebRequest permission the
    Expert Advisor depends on, which then fails on the next start in a way
    that looks like a networking fault rather than a lost setting.
    """
    _signal(running_pids(bottle), signal.SIGTERM)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not running_pids(bottle):
            break
        time.sleep(2)

    for pid in running_pids(bottle):
        log.warning("terminal %s did not exit; killing it", pid)
        with suppress(OSError):
            os.kill(pid, signal.SIGKILL)

    clear_strays(bottle)


def clear_strays(bottle: Path, grace: float = 6.0) -> int:
    """Clear whatever is left holding a prefix once no terminal is running.

    Always before a launch, never while a terminal is up: wineserver is asked
    first and given a moment, because it is the thing that writes the registry
    back, and only what ignores that is killed outright.
    """
    if is_running(bottle):
        return 0
    pids = stray_pids(bottle)
    if not pids:
        return 0

    log.info("clearing %d leftover process(es) holding %s", len(pids), bottle.name)
    _signal(pids, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline and stray_pids(bottle):
        time.sleep(1)
    _signal(stray_pids(bottle), signal.SIGKILL)
    return len(pids)


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

    provide_binary(terminal, experts / f"{source.stem}.mq5")
    set_expert_flags(terminal)

    presets = terminal / "MQL5/Presets"
    presets.mkdir(parents=True, exist_ok=True)
    (presets / "TradeZuluCopier.set").write_text(
        f"ServerUrl={callback_url}\nApiKey={api_key}\nPollSeconds=3\n",
        encoding="utf-8",
    )

    # Starting the expert from the terminal's own startup file means it is
    # attached before the first tick, so no chart has to be set up by hand.
    write_startup(terminal)


#: Compiled experts, kept between terminals so the same source is only ever
#: built once.
BUILDS = STATE_DIR / "builds"


def build_key(mq5: Path, terminal: Path) -> str | None:
    """What a compiled expert is only reusable within.

    Two things decide, and broker branding is not one of them -- a branded
    terminal is the same MetaQuotes engine with a different logo, and runs the
    same bytecode. What does decide is the source, obviously, and the
    terminal's own build: MetaTrader refuses an ``.ex5`` produced by a newer
    MetaEditor than itself, and brokers do not all ship the same build at the
    same time. The size of terminal64.exe stands in for the build number,
    which is not otherwise readable from out here.
    """
    exe = terminal / "terminal64.exe"
    try:
        digest = hashlib.sha1(mq5.read_bytes()).hexdigest()[:12]
        return f"{digest}-{exe.stat().st_size}"
    except OSError:
        return None


def provide_binary(terminal: Path, mq5: Path) -> None:
    """Give this terminal a compiled expert, building one only if nobody has.

    Compiling takes a MetaEditor run under Wine -- tens of seconds, and one
    more thing that can fail -- and it was being done again for every account,
    producing an identical file each time. It happens once per version now and
    every terminal after the first gets a copy.

    Not done in install.sh instead, tempting as that is: a terminal that has
    updated itself past the build the file was compiled for has to be able to
    rebuild it, and only this side knows when that has happened.
    """
    ex5 = mq5.with_suffix(".ex5")
    key = build_key(mq5, terminal)
    cached = BUILDS / f"{mq5.stem}-{key}.ex5" if key else None

    if cached is not None and cached.exists():
        if not ex5.exists() or ex5.read_bytes() != cached.read_bytes():
            shutil.copy2(cached, ex5)
            log.info("installed %s from the last build of it", ex5.name)
        return

    compile_expert(terminal, mq5)

    if cached is not None and ex5.exists():
        with suppress(OSError):
            BUILDS.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ex5, cached)


def compile_expert(terminal: Path, mq5: Path) -> None:
    """Build the expert, rather than hoping the terminal gets there first.

    MetaTrader does compile the sources it finds on startup, but it starts the
    expert named in the startup file *before* that finishes -- so on a fresh
    terminal there is nothing to run yet and the expert simply never appears,
    with no error anywhere to say why.
    """
    ex5 = mq5.with_suffix(".ex5")
    if ex5.exists() and ex5.stat().st_mtime >= mq5.stat().st_mtime:
        return

    editor = next(terminal.glob("metaeditor64.exe"), None) or next(
        terminal.glob("MetaEditor64.exe"), None
    )
    if editor is None:
        log.warning("no MetaEditor in %s; relying on the terminal to compile", terminal)
        return

    log.info("compiling %s", mq5.name)
    prefix = terminal
    while prefix.parent != prefix and prefix.name != "drive_c":
        prefix = prefix.parent
    script = (
        f'export WINEPREFIX="{prefix.parent}" WINEDEBUG=-all DISPLAY={DISPLAY}\n'
        f'unset PYTHONPATH PYTHONHOME\n'
        f'cd "{terminal}"\n'
        f'"{_runner()}" "{editor.name}" /compile:"MQL5\\\\Experts\\\\{mq5.name}" >/dev/null 2>&1\n'
    )
    subprocess.run(_flatpak_argv(script), capture_output=True, timeout=300)
    if ex5.exists():
        log.info("compiled %s", ex5.name)
    else:
        log.warning("%s did not compile; the terminal will try on its own", mq5.name)


#: What the Experts tab of MetaTrader's options writes. Only the URL list is
#: encrypted; these are plain text, so they can be set without a dialog.
EXPERT_FLAGS = {
    "Enabled": "1",   # allow algorithmic trading
    "Account": "0",   # ... and do not switch it off again on the first login
    "Profile": "0",
    "Chart": "0",
    "Api": "0",
}


def set_expert_flags(terminal: Path) -> None:
    """Make sure algorithmic trading stays on once the terminal logs in.

    A template belongs to no account, so a provisioned terminal's first login
    counts as the account changing -- and by default MetaTrader answers that
    by disabling algorithmic trading, several seconds after everything looked
    fine. The expert never runs and nothing says why.

    Writing the flags here rather than clicking them means it does not matter
    what state a template was left in.
    """
    config = terminal / "Config/common.ini"
    if not config.exists():
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(
            "[Experts]\n" + "".join(f"{k}={v}\n" for k, v in EXPERT_FLAGS.items()),
            encoding="utf-16-le",
        )
        return

    raw = config.read_bytes()
    encoding = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8"
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        log.warning("could not read %s; leaving it alone", config)
        return

    lines, seen, in_experts = [], set(), False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            if in_experts:
                lines += [f"{k}={v}" for k, v in EXPERT_FLAGS.items() if k not in seen]
                seen.update(EXPERT_FLAGS)
            in_experts = stripped.lower() == "[experts]"
        elif in_experts and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in EXPERT_FLAGS:
                seen.add(key)
                lines.append(f"{key}={EXPERT_FLAGS[key]}")
                continue
        lines.append(line)

    if in_experts:
        lines += [f"{k}={v}" for k, v in EXPERT_FLAGS.items() if k not in seen]
    elif not seen:
        lines += ["", "[Experts]"] + [f"{k}={v}" for k, v in EXPERT_FLAGS.items()]

    config.write_text("\n".join(lines) + "\n", encoding=encoding)
    log.info("algorithmic trading flags set in %s", config.name)


def write_startup(
    terminal: Path, login: str = "", server: str = "", password: str = ""
) -> None:
    """The terminal's startup file, optionally carrying credentials.

    MetaTrader takes login details from this file rather than from the command
    line -- the command-line switches are silently ignored by current builds,
    which looks exactly like a wrong password.

    Which means the password is briefly on disk in the clear. It is written
    immediately before the terminal starts and removed as soon as it has
    connected, because from then on MetaTrader keeps its own encrypted copy
    and this one is nothing but a liability.
    """
    # ExpertParameters is not optional: without it the terminal starts the
    # expert with empty inputs and it refuses to initialise, having no idea
    # where to report or what token to use. The preset file being present is
    # not enough -- it has to be named here.
    lines = [
        "[StartUp]",
        "Expert=TradeZuluCopier",
        "ExpertParameters=TradeZuluCopier.set",
        "Symbol=EURUSD",
        "Period=H1",
    ]
    if login and server and password:
        lines += ["", "[Common]", f"Login={login}", f"Password={password}", f"Server={server}"]
    (terminal / "tzstart.ini").write_text("\n".join(lines) + "\n", encoding="utf-8")


def launch(
    bottle: Path, terminal: Path, login: str, server: str, password: str, display: str = ""
) -> None:
    """Start the terminal, logged in, on its own virtual display.

    Credentials go on the command line rather than into a file. MetaTrader
    stores what it needs in its own encrypted form once it has connected, and
    a password written to disk in the clear would outlive this call.
    """
    display = display or DISPLAY
    log.info("starting terminal for %s on %s (display %s)", login, server, display)
    write_startup(terminal, login, server, password)
    script = (
        f'export WINEPREFIX="{bottle}" WINEDEBUG=-all DISPLAY={display}\n'
        f'unset PYTHONPATH PYTHONHOME\n'
        f'cd "{terminal}"\n'
        f'setsid "{_runner()}" terminal64.exe /portable /config:tzstart.ini '
        f'>/dev/null 2>&1 < /dev/null\n'
    )
    _flatpak_spawn(script)


# --- the one thing that still needs a GUI ------------------------------------


def allow_webrequest(login: str, url: str, display: str = "") -> bool:
    """Add TradeZulu to the terminal's WebRequest allowlist.

    MetaTrader keeps this list encrypted in its own config, so it cannot be
    written from outside; the only way in is the dialog. Driving it takes a
    couple of seconds and happens once per terminal, which is a fair price for
    not asking the user to do it -- and asking them would defeat the point,
    since an Expert Advisor without this permission fails silently.
    """
    if shutil.which("xdotool") is None:
        # Worth saying plainly rather than crashing: the terminal is running
        # and everything else about it is correct, so the fix is one package
        # rather than anything to undo.
        log.error(
            "xdotool is not installed, so %s cannot be allowed through "
            "MetaTrader's WebRequest list and its Expert Advisor will not "
            "reach TradeZulu. apt install xdotool, then this will retry.",
            url,
        )
        return False

    env = {**os.environ, "DISPLAY": display or DISPLAY}

    found = subprocess.run(
        ["xdotool", "search", "--name", re.escape(login)],
        env=env, capture_output=True, text=True,
    )
    window = found.stdout.split()[-1] if found.stdout.strip() else ""
    if not window:
        log.warning("no terminal window for %s yet; will retry", login)
        return False

    before = _windows(env)
    subprocess.run(["xdotool", "windowactivate", window], env=env, capture_output=True)
    time.sleep(2)
    subprocess.run(["xdotool", "key", "--window", window, "ctrl+o"], env=env, capture_output=True)

    dialog = _await_new_window(env, before)
    if dialog is None:
        log.warning("the Options dialog did not open for %s; will retry", login)
        return False

    box = _geometry(env, dialog)
    if box is None:
        log.warning("could not measure the Options dialog for %s; will retry", login)
        return False
    left, top, width, height = box

    def click(fx: float, fy: float, repeat: int = 1) -> None:
        """Click a point given as a fraction of the dialog, not of the screen."""
        args = ["xdotool", "mousemove", str(left + int(width * fx)), str(top + int(height * fy))]
        if repeat > 1:
            args += ["click", "--repeat", str(repeat), "1"]
        else:
            args += ["click", "1"]
        subprocess.run(args, env=env, capture_output=True)

    # Measured against the dialog itself rather than the screen. The dialog is
    # a fixed 620x389 and opens wherever the window manager puts it, so screen
    # coordinates were only ever right for the position it happened to open at
    # while they were written -- one of the old ones landed outside the dialog
    # altogether.
    click(0.26, 0.04)          # Experts tab
    time.sleep(1)
    click(0.24, 0.67, repeat=2)  # the "add new URL" row, to start editing
    time.sleep(2)
    subprocess.run(["xdotool", "type", "--delay", "60", url], env=env, capture_output=True)
    time.sleep(1)
    subprocess.run(["xdotool", "key", "Return"], env=env, capture_output=True)
    time.sleep(1)
    click(0.66, 0.95)          # OK
    time.sleep(2)

    # The dialog closing is the only part of this that can be checked from
    # outside: if it is still up, a click missed and nothing was saved.
    if dialog in _windows(env):
        log.warning(
            "the Options dialog for %s did not close, so the WebRequest entry "
            "was probably not saved; will retry",
            login,
        )
        subprocess.run(["xdotool", "key", "--window", dialog, "Escape"], env=env, capture_output=True)
        return False

    log.info("entered %s into the WebRequest list for %s", url, login)
    return True


#: How many times to drive the Options dialog before giving up and saying so.
#: Each attempt costs a few seconds and adds a list entry if it half-worked, so
#: this is deliberately small -- the point is to stop quietly retrying forever.
WEBREQUEST_ATTEMPTS = 3


def _windows(env: dict[str, str]) -> set[str]:
    result = subprocess.run(
        ["xdotool", "search", "--name", "."], env=env, capture_output=True, text=True
    )
    return set(result.stdout.split())


def _await_new_window(
    env: dict[str, str], before: set[str], timeout: float = 12.0
) -> str | None:
    """The window that appeared, waited for rather than slept through.

    Found by being new rather than by its title: the dialog is called
    "Options" in English and something else in every other language, and a
    fixed sleep is either too short on a loaded machine or wasted time on a
    quick one.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.5)
        new = _windows(env) - before
        for candidate in new:
            box = _geometry(env, candidate)
            # Skip Wine's invisible helpers -- input methods and the like,
            # which are a pixel or two square.
            if box and box[2] > 200 and box[3] > 150:
                return candidate
    return None


def _geometry(env: dict[str, str], window: str) -> tuple[int, int, int, int] | None:
    result = subprocess.run(
        ["xdotool", "getwindowgeometry", "--shell", window],
        env=env, capture_output=True, text=True,
    )
    values: dict[str, int] = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition("=")
        if value.strip().lstrip("-").isdigit():
            values[key.strip()] = int(value)
    try:
        return values["X"], values["Y"], values["WIDTH"], values["HEIGHT"]
    except KeyError:
        return None


# --- reconcile ---------------------------------------------------------------


#: How long a freshly started terminal has to log in and report in before
#: something is taken to be wrong with it. A healthy one takes under a minute:
#: MetaTrader logs in, the expert initialises, and it polls every few seconds.
STARTUP_GRACE = 300.0

#: How long a terminal that *was* reporting may go quiet before it is
#: restarted. Generous, because restarting one that is merely between polls
#: costs a minute of copying for nothing.
SILENCE_LIMIT = 600.0

#: Restarts before the prefix itself is suspected and rebuilt from the
#: template, and rebuilds before this stops and asks for a person.
RESTARTS_BEFORE_REBUILD = 2
REBUILDS_BEFORE_GIVING_UP = 2


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def health(last_seen: datetime | None, launched: datetime | None, now: datetime) -> str:
    """What to make of a terminal that is running.

    "Running" is the weakest possible statement about a MetaTrader terminal.
    It can be running and sitting on a login the broker refused, or on an
    update dialog, or with an Expert Advisor that cannot reach TradeZulu --
    all of which look identical from the outside and none of which copy a
    trade. The only evidence that a terminal *works* is that its expert
    reached the server, so that is what is measured.
    """
    if last_seen is not None and (now - last_seen).total_seconds() <= SILENCE_LIMIT:
        return "reporting"
    if launched is not None and (now - launched).total_seconds() < STARTUP_GRACE:
        return "settling"
    return "never-reported" if last_seen is None else "gone-quiet"


#: What a terminal is doing, in words the journal can show without knowing
#: anything about Wine, prefixes or MetaTrader. Ordered worst to best only for
#: reading; nothing depends on the order.
PHASES = ("failed", "quiet", "installing", "starting", "retrying", "running")


def terminal_status(spec: dict, bottle: Path, state: dict, now: datetime) -> dict:
    """One account's terminal, described for somebody looking at the journal.

    Everything here is already known -- it is the same evidence supervise()
    acts on -- it simply never left this machine. "No terminal yet" was the
    only thing the accounts page could say, whether MetaTrader was still
    installing, sitting on a refused login, or given up on twenty minutes ago,
    and those want very different reactions from the person reading it.
    """
    last_seen = _parse_time(spec.get("last_seen"))
    launched = _parse_time(state.get("launched"))
    verdict = health(last_seen, launched, now)
    attempts = int(state.get("restarts") or 0) + int(state.get("rebuilds") or 0)

    if state.get("gave_up"):
        return {
            "phase": "failed",
            "message": (
                "Restarting and rebuilding both failed. Check the account number, "
                "password and server, then use Forget and add it again."
            ),
            "attempts": attempts,
        }

    if verdict == "reporting":
        return {"phase": "running", "message": "Its Expert Advisor is reporting in.", "attempts": 0}

    if not bottle.exists() or terminal_dir(bottle) is None:
        return {
            "phase": "installing",
            "message": "Building its MetaTrader install. This takes a few minutes the first time.",
            "attempts": attempts,
        }

    if attempts:
        return {
            "phase": "retrying",
            "message": f"It has not reported in; trying again (attempt {attempts + 1}).",
            "attempts": attempts,
        }

    if verdict == "settling" or (launched is not None and last_seen is None):
        return {
            "phase": "starting",
            "message": "Started, waiting for its Expert Advisor to report in.",
            "attempts": attempts,
        }

    if verdict == "gone-quiet":
        return {
            "phase": "quiet",
            "message": "It was reporting and has stopped.",
            "attempts": attempts,
        }

    return {
        "phase": "starting",
        "message": "Waiting for a terminal to be started for it.",
        "attempts": attempts,
    }


def report_status(base_url: str, token: str, states: list[dict]) -> None:
    """Tell the server what each terminal is doing.

    Best-effort on purpose: this is how the accounts page stops saying "no
    terminal yet" for twenty minutes, and it is not worth failing a
    provisioning cycle over. The next cycle sends the state again anyway.
    """
    if not states or not base_url:
        return
    # Everything inside the guard, including building the request: a malformed
    # base URL raises when the Request is constructed, not when it is sent, and
    # that would take down the provisioning cycle this is only commentary on.
    try:
        request = urllib.request.Request(
            base_url.rstrip("/") + "/api/agent/terminals/state",
            data=json.dumps({"terminals": states}).encode(),
            headers={"X-API-Key": token, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20):
            pass
    except Exception as error:  # noqa: BLE001 - reporting must not break provisioning
        log.debug("could not report terminal status: %s", error)


def reconcile(plan: Plan, template: Path, expert: Path, settled: bool = True) -> None:
    """Make the terminals on this machine match what the server asks for.

    ``settled`` says whether the previous cycle also reached the server. When
    it did not -- the site was restarted, or this process has just started --
    every terminal looks like it has gone quiet, because nothing could record
    a poll while the server was down. Restarting them all on that evidence
    would turn a minute of site downtime into a fleet-wide outage, so silence
    is only acted on once we have been watching continuously.
    """
    #: login -> the account already given a terminal for it this cycle.
    claimed: dict[str, int] = {}

    for spec in plan.terminals:
        if not spec.get("enabled"):
            continue

        # One terminal per broker account, whatever the server says. Two rows
        # for the same login is a fault upstream -- it used to happen when an
        # imported statement created a second "master" -- but the consequence
        # is here: two terminals log into the same account, both run the
        # Expert Advisor, and both act on every command the copier sends, so
        # the order is placed twice.
        login = str(spec.get("login") or "").strip()
        if login in claimed:
            log.error(
                "accounts %s and %s are both %s. Only one terminal is started for "
                "it; remove the duplicate account in TradeZulu (Accounts -> "
                "Forget) and its terminal is cleared up on the next cycle.",
                claimed[login], spec.get("account_id"), login,
            )
            continue
        claimed[login] = int(spec["account_id"])

        try:
            ensure_terminal(spec, plan, template, expert, settled)
        except Exception:  # noqa: BLE001 - one bad account must not stop the rest
            log.exception("could not reconcile account %s", spec.get("account_id"))

    reap(plan)

    # Read back after the pass, so what is reported is where each terminal
    # ended up rather than where it was when the cycle began.
    now = datetime.now(timezone.utc)
    report_status(
        plan.base_url,
        plan.token,
        [
            dict(
                account_id=int(spec["account_id"]),
                display=display_for(int(spec["account_id"])),
                vnc_port=vnc_port_for(display_for(int(spec["account_id"]))),
                **terminal_status(
                    spec,
                    bottle_for(int(spec["account_id"])),
                    load_state(int(spec["account_id"])),
                    now,
                ),
            )
            for spec in plan.terminals
            if spec.get("enabled") and spec.get("account_id") is not None
        ],
    )


def ensure_terminal(
    spec: dict, plan: Plan, fallback: Path, expert: Path, settled: bool = True
) -> None:
    """Bring one account's terminal to where it should be."""
    account_id = int(spec["account_id"])
    bottle = bottle_for(account_id)
    state = load_state(account_id)

    # Its own screen, and its own VNC server on it. Done every cycle rather
    # than only at launch: both survive this process restarting, and a display
    # that died takes its terminal with it, so the next pass finds no terminal
    # running and starts one on the screen this just brought back.
    display = display_for(account_id)
    if not ensure_display(display, required=False):
        return
    ensure_vnc(display, plan.vnc_bind)

    # Somebody pressed Restart in the web interface. Stopping is all that is
    # done here: the reconcile below finds no terminal running and starts one,
    # which is the same path a terminal that died on its own takes, so there
    # is no second way to start a terminal that can rot.
    #
    # The token is remembered rather than acknowledged. A request this process
    # has already acted on looks identical to one it has not, unless it keeps
    # the last one it saw -- and a flag cleared over the network is a flag that
    # is cleared twice, or not at all, when either side restarts mid-way.
    token = str(spec.get("restart_token") or "")
    if token and token != str(state.get("restart_token") or ""):
        state["restart_token"] = token
        save_state(account_id, state)
        if is_running(bottle):
            log.info("restart asked for %s; stopping it", spec.get("login"))
            stop_terminal(bottle)
            return

    # A prefix is named after the account row, and a row's id can be handed out
    # again after the account it belonged to was forgotten. Inheriting the last
    # account's MetaTrader install -- its server list, its saved login, its
    # charts -- is the "leftover from before that is in the way" that no amount
    # of restarting clears, so identity is checked rather than assumed.
    owner = str(state.get("login") or "")
    if bottle.exists() and owner and owner != str(spec["login"]):
        discard_prefix(bottle, f"it belongs to account {owner}, not {spec['login']}")
        state = {}

    if not bottle.exists():
        clone_template(
            template_for(spec.get("broker", ""), spec.get("server", ""), fallback), bottle
        )
        state.pop("gave_up", None)

    terminal = terminal_dir(bottle)
    if terminal is None:
        log.error("no terminal64.exe in %s -- is the template complete?", bottle)
        return

    if is_running(bottle):
        supervise(spec, plan, bottle, state, settled)
        return

    if state.get("gave_up"):
        return

    # A launch already under way. MetaTrader takes a while to get from "the
    # sandbox is up" to "terminal64.exe exists" -- longer on the first start of
    # a prefix, longer still if it decides to install an update on the way --
    # and for that stretch there is no terminal process to find. Launching
    # again because of it would put two terminals on one account, which is the
    # one outcome worth going out of the way to avoid.
    launched = _parse_time(state.get("launched"))
    if launched is not None and stray_pids(bottle):
        waiting = (datetime.now(timezone.utc) - launched).total_seconds()
        if waiting < STARTUP_GRACE:
            log.info("%s is still starting (%ds); not launching another", spec["login"], waiting)
            return
        log.warning(
            "%s has been starting for %ds with no terminal to show for it; "
            "clearing it up and trying again",
            spec["login"], waiting,
        )

    # Whatever a previous attempt left holding this prefix goes first. A stale
    # wineserver among it will happily accept the new terminal and then serve
    # it nothing, which looks like MetaTrader hanging on startup.
    clear_strays(bottle)

    install_expert(terminal, expert, plan.callback_url, plan.api_key)
    launch(
        bottle, terminal, spec["login"], spec["server"], spec["password"],
        display_for(account_id),
    )

    state.update(
        login=str(spec["login"]),
        server=str(spec.get("server") or ""),
        launched=datetime.now(timezone.utc).isoformat(),
    )
    save_state(account_id, state)

    # Give the terminal time to reach a login before touching its window.
    time.sleep(45)

    # The password has done its job. MetaTrader keeps its own encrypted copy
    # from here on, so leaving this one on disk would buy nothing and risk
    # everything.
    write_startup(terminal)


def supervise(
    spec: dict, plan: Plan, bottle: Path, state: dict, settled: bool = True
) -> None:
    """Decide what a running terminal needs, if anything.

    This runs every cycle rather than only in the one where a terminal was
    started. It used to be reachable only immediately after a launch, so the
    retry ladder below could never advance past its first rung: a terminal
    that came up and stayed silent was tried once and then left alone for ever.
    """
    account_id = int(spec["account_id"])
    login = str(spec["login"])
    now = datetime.now(timezone.utc)
    state.setdefault("login", login)
    state.setdefault("server", str(spec.get("server") or ""))

    verdict = health(_parse_time(spec.get("last_seen")), _parse_time(state.get("launched")), now)

    if verdict == "reporting":
        # Everything it was ever failing at, it is no longer failing at.
        if any(state.get(key) for key in ("webrequest_attempts", "restarts", "rebuilds")):
            log.info("%s is reporting in again", login)
        for key in ("webrequest_attempts", "restarts", "rebuilds", "gave_up"):
            state.pop(key, None)
        state["webrequest_ok"] = True
        save_state(account_id, state)
        return

    if verdict == "settling" or state.get("gave_up"):
        return

    if verdict == "never-reported":
        # It has never worked, so the WebRequest permission is the first
        # suspect: without it the expert runs, reports nothing, and the
        # terminal looks perfectly healthy. Confirmation only ever comes from
        # the expert reaching the server, never from the clicks appearing to
        # land -- a dialog driven by coordinates can miss and still succeed.
        attempts = int(state.get("webrequest_attempts") or 0)
        if attempts < WEBREQUEST_ATTEMPTS and not state.get("webrequest_ok"):
            state["webrequest_attempts"] = attempts + 1
            save_state(account_id, state)
            log.info(
                "%s has not reported in; granting WebRequest permission (attempt %d)",
                login, attempts + 1,
            )
            allow_webrequest(login, plan.callback_url, display_for(account_id))
            return
        recycle(spec, bottle, state, "it has never reported in", plan)
        return

    # gone-quiet: it worked and has stopped.
    if not settled:
        log.info("%s has gone quiet, but so has everything else; waiting a cycle", login)
        return
    recycle(spec, bottle, state, "it stopped reporting in", plan)


def recycle(spec: dict, bottle: Path, state: dict, why: str, plan: Plan) -> None:
    """Restart a terminal, then rebuild it, then stop and say so.

    Each rung is tried because the one before it did not help, which is the
    only honest reason to escalate. Nothing here loops for ever: the counts
    live outside the prefix, so deleting the prefix does not reset them.
    """
    account_id = int(spec["account_id"])
    login = str(spec["login"])
    restarts = int(state.get("restarts") or 0)
    rebuilds = int(state.get("rebuilds") or 0)

    if restarts < RESTARTS_BEFORE_REBUILD:
        state["restarts"] = restarts + 1
        save_state(account_id, state)
        log.warning("%s: %s; restarting its terminal (%d)", login, why, restarts + 1)
        stop_terminal(bottle)
        return  # the next cycle sees no terminal and starts a fresh one

    if rebuilds < REBUILDS_BEFORE_GIVING_UP:
        state.update(rebuilds=rebuilds + 1, restarts=0)
        state.pop("webrequest_attempts", None)
        state.pop("webrequest_ok", None)
        save_state(account_id, state)
        log.warning(
            "%s: %s after %d restarts; rebuilding its MetaTrader install from "
            "the template (%d)",
            login, why, restarts, rebuilds + 1,
        )
        discard_prefix(bottle, f"account {login} could not be made to work")
        return

    state["gave_up"] = True
    save_state(account_id, state)
    log.error(
        "%s: %s, and neither restarting nor rebuilding its terminal helped. "
        "Nothing further will be tried automatically. Look at it with "
        "agent/tz-view.sh watch, check the password and server are right, and "
        "that %s is in Tools -> Options -> Expert Advisors -> Allow WebRequest. "
        "Then: agent/tz_provision.py --reset %s",
        login, why, plan.callback_url, login,
    )


def discard_prefix(bottle: Path, why: str) -> None:
    """Delete one account's MetaTrader install, terminal and all."""
    log.warning("removing %s: %s", bottle.name, why)
    stop_terminal(bottle)
    clear_strays(bottle)
    shutil.rmtree(bottle, ignore_errors=True)


def purge_terminal(account_id: int) -> None:
    """Remove every trace of one account's terminal from this machine."""
    discard_prefix(bottle_for(account_id), f"account {account_id} is being cleared")
    forget_state(account_id)


def reap(plan: Plan) -> None:
    """Clear up terminals for accounts TradeZulu no longer has.

    Forgetting an account in the web interface deleted its rows and left its
    MetaTrader install running here for good -- logged in, polling, refused
    with a 404 every two seconds, and holding the prefix name that the next
    account added would be given. Tearing the whole machine down with
    ``uninstall.sh --all`` was the only way to clear it, which is a heavy
    answer to "I removed one account".

    Only accounts the server *listed* are considered. An older server that
    says nothing about what it knows gets nothing removed, because "not in the
    plan" is also what an account with no password looks like, and deleting a
    working install over a missing field is not a recoverable mistake.
    """
    if plan.known_accounts is None:
        return
    for prefix in sorted((BOTTLES / "bottles").glob("tz-*")):
        account_id = account_of(prefix)
        if account_id is None or account_id in plan.known_accounts:
            continue
        log.info("account %s is gone from TradeZulu; removing its terminal", account_id)
        purge_terminal(account_id)

    for leftover in sorted(STATE_DIR.glob("*.json")):
        with suppress(ValueError):
            if int(leftover.stem) not in plan.known_accounts:
                leftover.unlink(missing_ok=True)


# --- weekly restart -----------------------------------------------------------

#: When the last maintenance pass finished.
STATE = BOTTLES / ".tz-last-maintenance"


def maintenance_due(weekday: int, hour: int, now: datetime | None = None) -> bool:
    """Whether it is time for the weekly restart.

    The window is checked rather than scheduled, so a machine that was off on
    Sunday still gets its restart when it comes back rather than skipping a
    week.

    Running twice is prevented by the date of the last pass, not by how long
    ago it was. "Seven days" is wrong at the boundary: a pass that finishes at
    03:05 is five minutes short of seven days when the next Sunday's 03:00
    window opens, so a week would be silently skipped every time.
    """
    now = now or datetime.now()
    if now.weekday() != weekday or now.hour < hour:
        return False
    try:
        last = datetime.fromtimestamp(STATE.stat().st_mtime)
    except OSError:
        return True
    return last.date() < now.date()


def refresh_template(template: Path) -> None:
    """Start a template long enough for it to update itself, then stop it.

    New accounts are copies of these, so a template left behind means every
    account created from it starts with an update waiting -- which is the
    problem this whole pass exists to avoid, just deferred.
    """
    terminal = terminal_dir(template)
    if terminal is None:
        return
    log.info("refreshing template %s", template.name)
    script = (
        f'export WINEPREFIX="{template}" WINEDEBUG=-all DISPLAY={DISPLAY}\n'
        f'unset PYTHONPATH PYTHONHOME\n'
        f'cd "{terminal}"\n'
        f'setsid "{_runner()}" terminal64.exe /portable >/dev/null 2>&1 < /dev/null\n'
    )
    _flatpak_spawn(script)
    time.sleep(240)
    stop_terminal(template)


def run_maintenance(plan: Plan, fallback: Path) -> None:
    """Stop every terminal so that the next cycle starts it fresh.

    MetaTrader downloads updates while it runs and then asks to restart to
    install them. Left alone that question sits on screen for days, and a
    terminal waiting on it is not copying trades -- the failure arrives on
    whatever day the broker happens to ship a build, not on a day anyone
    chose. Restarting on a schedule applies updates during a quiet hour
    instead, with no dialog, because a terminal that is already stopped
    installs them on the way up.

    Nothing is started here. The reconcile that follows sees no terminal
    running and brings each one back, which is the same path used for a
    terminal that died for any other reason.
    """
    log.info("weekly maintenance: restarting terminals to pick up updates")

    for spec in plan.terminals:
        bottle = bottle_for(int(spec["account_id"]))
        if is_running(bottle):
            log.info("stopping %s", bottle.name)
            stop_terminal(bottle)

    seen: set[Path] = set()
    for spec in plan.terminals:
        template = template_for(spec.get("broker", ""), spec.get("server", ""), fallback)
        if template.exists() and template not in seen:
            seen.add(template)
            refresh_template(template)

    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.touch()
    log.info("weekly maintenance done")


# --- clearing up by hand ------------------------------------------------------


def resolve_targets(targets: list[str], url: str, token: str) -> set[int]:
    """Turn what someone typed into account ids.

    An account number is what a person knows -- it is on their statements and
    in the web interface -- while the prefix on disk is named after a database
    row nobody has ever seen. Both are accepted, and so is ``all``.
    """
    if any(target.lower() == "all" for target in targets):
        return {
            account_id
            for prefix in (BOTTLES / "bottles").glob("tz-*")
            if (account_id := account_of(prefix)) is not None
        }

    #: login -> account id, from the server if it will talk to us and from what
    #: was recorded here if it will not. Neither is required to reset by id.
    by_login: dict[str, int] = {}
    with suppress(Exception):
        for spec in fetch_plan(url, token).terminals:
            by_login[str(spec["login"]).strip()] = int(spec["account_id"])
    for path in STATE_DIR.glob("*.json"):
        with suppress(ValueError):
            login = str(load_state(int(path.stem)).get("login") or "").strip()
            by_login.setdefault(login, int(path.stem))

    resolved: set[int] = set()
    for target in targets:
        target = target.strip()
        if target in by_login:
            resolved.add(by_login[target])
        elif target.isdigit() and bottle_for(int(target)).exists():
            resolved.add(int(target))
        else:
            log.error("no terminal here for %r", target)
    return resolved


def reset(targets: list[str], url: str, token: str) -> int:
    """Stop and delete terminals so they are built again from scratch.

    This is the "clear it up and start over" that does not involve
    uninstalling anything. Nothing in TradeZulu itself is touched -- no
    account, no trade, no password -- so the next provisioning cycle simply
    finds no terminal for an account that should have one, and makes it.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
    ids = resolve_targets(targets, url, token)
    if not ids:
        log.error("nothing matched; there is no terminal here for %s", ", ".join(targets))
        return 1

    for account_id in sorted(ids):
        bottle = bottle_for(account_id)
        login = str(load_state(account_id).get("login") or account_id)
        log.info("clearing %s (account %s)", login, bottle.name)
        purge_terminal(account_id)

    log.info(
        "done. %d terminal(s) cleared; each account that still has credentials "
        "gets a fresh one within a minute or two.",
        len(ids),
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.getenv("TZ_URL", "http://127.0.0.1:8420"))
    parser.add_argument("--token", default=os.getenv("TZ_INGEST_TOKEN", ""))
    parser.add_argument(
        "--template",
        type=Path,
        default=BOTTLES / "bottles" / "tz-template-default",
        help="Fallback prefix, used for brokers with no template of their own.",
    )
    parser.add_argument(
        "--expert",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "mt5" / "TradeZuluCopier.mq5",
    )
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    # Sunday by default, in the small hours: the weekend gap between the
    # Friday close and the Sunday open is the only time restarting a terminal
    # cannot interrupt a trade.
    parser.add_argument(
        "--maintenance-day",
        type=int,
        default=int(os.getenv("TZ_MAINTENANCE_DAY", "6")),
        help="Weekday for the update restart, Monday=0 (default Sunday).",
    )
    parser.add_argument(
        "--maintenance-hour",
        type=int,
        default=int(os.getenv("TZ_MAINTENANCE_HOUR", "3")),
        help="Hour of that day, local time (default 3am).",
    )
    parser.add_argument(
        "--maintenance-now",
        action="store_true",
        help="Run the weekly restart immediately, then carry on as normal.",
    )
    parser.add_argument(
        "--reset",
        nargs="+",
        metavar="ACCOUNT",
        help="Stop and delete these terminals, then exit; they are rebuilt on "
        "the next cycle. Takes account numbers, or 'all'. Nothing in the "
        "journal is touched.",
    )
    args = parser.parse_args()

    if args.reset:
        return reset(args.reset, args.url, args.token)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )

    if not args.token:
        log.error("no API token; set TZ_INGEST_TOKEN or pass --token")
        return 2
    if not args.template.exists():
        log.error(
            "no template prefix at %s -- run agent/make-template.sh to build one. "
            "Every account is a copy of it.",
            args.template,
        )
        return 2

    ensure_display()

    forced = args.maintenance_now
    #: When the server was last reachable. A terminal that has gone quiet is
    #: only evidence of anything if we were in a position to hear it.
    last_ok: float | None = None
    while True:
        try:
            plan = fetch_plan(args.url, args.token)
            settled = last_ok is not None and time.monotonic() - last_ok < args.interval * 3
            # Before reconciling, not after: maintenance only stops terminals,
            # and the reconcile that follows is what brings them back. Doing it
            # the other way round would leave everything down until the next
            # cycle.
            # The server's window wins; the flags remain as a fallback for a
            # provisioner that cannot reach it, and as an override for testing.
            weekday = int(plan.maintenance.get("weekday", args.maintenance_day))
            hour = int(plan.maintenance.get("hour", args.maintenance_hour))
            if forced or maintenance_due(weekday, hour):
                forced = False
                run_maintenance(plan, args.template)
            reconcile(plan, args.template, args.expert, settled=settled)
            last_ok = time.monotonic()
        except urllib.error.URLError as error:
            log.warning("TradeZulu not reachable at %s: %s", args.url, error)
        except Exception:  # noqa: BLE001 - a bad cycle must not kill the daemon
            log.exception("provisioning cycle failed")
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
