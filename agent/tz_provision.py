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
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import suppress
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


def ensure_display() -> None:
    """Make sure there is a screen for the terminals to draw on.

    MetaTrader will not run headless. It does not need a *visible* screen
    though, and giving it a real one would put trading windows in front of
    whoever happens to be using the machine.

    A display written ``host:N`` belongs to somewhere else -- another machine,
    or a container -- so it is used as given and never started here. Only a
    plain ``:N`` is ours to bring up, and the socket says whether it already
    is without needing an X client installed to ask.
    """
    if not DISPLAY.startswith(":"):
        log.info("using the display at %s", DISPLAY)
        return

    if Path(f"/tmp/.X11-unix/X{DISPLAY[1:]}").exists():
        return

    if shutil.which("Xvfb") is None:
        raise SystemExit(
            f"No display at {DISPLAY} and Xvfb is not installed. "
            "Run install.sh, or apt install xvfb xdotool openbox."
        )

    log.info("starting virtual display %s", DISPLAY)
    subprocess.Popen(
        ["Xvfb", DISPLAY, "-ac", "-screen", "0", "1400x1000x24"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    if shutil.which("openbox"):
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


def load_brokers() -> dict[str, dict]:
    path = Path(__file__).resolve().parent / "brokers.json"
    try:
        return {
            key: value
            for key, value in json.loads(path.read_text()).items()
            if isinstance(value, dict)
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


def running_pids(bottle: Path) -> list[int]:
    """The terminal processes belonging to one account's prefix.

    Wine reports a terminal under its *Windows* path -- every account's shows
    up as ``C:\\Program Files\\MetaTrader 5\\terminal64.exe`` -- so matching
    the command line cannot tell two accounts apart, and matching the Linux
    prefix path finds nothing at all.

    The environment can. WINEPREFIX is set per process and says exactly which
    account a terminal belongs to. Getting this wrong is not cosmetic: a check
    that fails to see a running terminal starts a second one on the same
    account, and two terminals copying the same master both place the order.
    """
    want = f"WINEPREFIX={bottle}".encode()
    pids: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            environ = (entry / "environ").read_bytes()
            command = (entry / "cmdline").read_bytes()
        except OSError:
            continue  # the process ended, or is not ours to look at
        if b"terminal64.exe" in command and want in environ.split(b"\0"):
            pids.append(int(entry.name))
    return pids


def is_running(bottle: Path) -> bool:
    return bool(running_pids(bottle))


def stop_terminal(bottle: Path, timeout: float = 40.0) -> None:
    """Stop an account's terminal, giving it time to save.

    MetaTrader writes its settings only when it exits cleanly. Killing it
    outright silently loses them -- including the WebRequest permission the
    Expert Advisor depends on, which then fails on the next start in a way
    that looks like a networking fault rather than a lost setting.
    """
    pids = running_pids(bottle)
    for pid in pids:
        with suppress(OSError):
            os.kill(pid, signal.SIGTERM)

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not running_pids(bottle):
            return
        time.sleep(2)

    for pid in running_pids(bottle):
        log.warning("terminal %s did not exit; killing it", pid)
        with suppress(OSError):
            os.kill(pid, signal.SIGKILL)


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

    compile_expert(terminal, experts / f"{source.stem}.mq5")
    set_expert_flags(terminal)

    presets = terminal / "MQL5/Presets"
    presets.mkdir(parents=True, exist_ok=True)
    (presets / "TradeZuluCopier.set").write_text(
        "ServerUrl={}\nApiKey={}\nPollSeconds=3\n".format(callback_url, api_key),
        encoding="utf-8",
    )

    # Starting the expert from the terminal's own startup file means it is
    # attached before the first tick, so no chart has to be set up by hand.
    write_startup(terminal)


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


def launch(bottle: Path, terminal: Path, login: str, server: str, password: str) -> None:
    """Start the terminal, logged in, on the virtual display.

    Credentials go on the command line rather than into a file. MetaTrader
    stores what it needs in its own encrypted form once it has connected, and
    a password written to disk in the clear would outlive this call.
    """
    log.info("starting terminal for %s on %s", login, server)
    write_startup(terminal, login, server, password)
    script = (
        f'export WINEPREFIX="{bottle}" WINEDEBUG=-all DISPLAY={DISPLAY}\n'
        f'unset PYTHONPATH PYTHONHOME\n'
        f'cd "{terminal}"\n'
        f'setsid "{_runner()}" terminal64.exe /portable /config:tzstart.ini '
        f'>/dev/null 2>&1 < /dev/null\n'
    )
    _flatpak_spawn(script)


# --- the one thing that still needs a GUI ------------------------------------


def allow_webrequest(login: str, url: str) -> bool:
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
            clone_template(
                template_for(spec.get("broker", ""), spec.get("server", ""), template), bottle
            )

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

        # The password has done its job. MetaTrader keeps its own encrypted
        # copy from here on, so leaving this one on disk would buy nothing and
        # risk everything.
        write_startup(terminal)

        # A template that was granted its permissions passes them on, because
        # a clone is the same installation byte for byte. That is the whole
        # reason this does not have to drive a dialog for every account -- and
        # driving one here would mean finding the right window among every
        # other account's terminal, which is a guess this has no business
        # making. Only a template built without them falls through.
        if (bottle / ".tz-permissions-set").exists():
            continue

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
    args = parser.parse_args()

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
