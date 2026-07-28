#!/usr/bin/env bash
# Bring up a headless MetaTrader 5 under Wine and start the read-only bridge.
#
# MetaTrader's client-server protocol is proprietary, so a real terminal is the
# only way to reach an account with just a server, a login and a password. This
# script is what keeps that terminal out of your way.
#
# First boot downloads Wine's prefix, a Windows Python and the MetaTrader
# installer into /wine. Expect 5-15 minutes. Keep /wine on a volume and every
# later start takes seconds.
set -euo pipefail

PYTHON_VERSION="${WINE_PYTHON_VERSION:-3.11.9}"
# numpy 2.x calls ucrtbase.dll.crealf, which Wine 8 (Debian bookworm) does not
# implement — importing it aborts the process before the bridge ever starts.
# 1.26.4 is the last 1.x release and satisfies MetaTrader5's numpy>=1.7.
NUMPY_SPEC="${WINE_NUMPY_SPEC:-numpy==1.26.4}"
# Pinnable: the package's IPC layer is the part Wine struggles with, so being
# able to move between wheel versions without rebuilding matters.
MT5_PACKAGE_SPEC="${MT5_PACKAGE_SPEC:-MetaTrader5}"
PYTHON_EXE_URL="${WINE_PYTHON_URL:-https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-amd64.exe}"
WINE_MONO_URL="${WINE_MONO_URL:-https://dl.winehq.org/wine/wine-mono/10.3.0/wine-mono-10.3.0-x86.msi}"
# MetaQuotes serves every broker's build from one predictable shape:
#   https://download.terminal.free/cdn/web/<company.path>/mt5/<name>setup.exe
# e.g. vantage.markets.pty/mt5/vantagemarkets5setup.exe. A branded build
# installs under its own name in Program Files, which is why the terminal is
# discovered below rather than assumed. Brokers who ship no build of their own
# (Falcon, for one) work with the generic default.
MT5_SETUP_URL="${MT5_SETUP_URL:-https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe}"

PYTHON_DIR="${WINEPREFIX}/drive_c/Python"
PYTHON_DIR_WIN="C:\\Python"
WINE_PYTHON_UNIX="${PYTHON_DIR}/python.exe"
WINE_PYTHON="${PYTHON_DIR}/python.exe"
MT5_DIR="${WINEPREFIX}/drive_c/Program Files/MetaTrader 5"
MT5_TERMINAL="${MT5_DIR}/terminal64.exe"

# A broker's own build installs under its own name, so the default above is
# only a starting guess; anything already installed wins.
existing_terminal="$(find "${WINEPREFIX}/drive_c/Program Files" -maxdepth 2 \
  -name terminal64.exe 2>/dev/null | head -n1)"
if [ -n "${existing_terminal}" ]; then
  MT5_TERMINAL="${existing_terminal}"
  MT5_DIR="$(dirname "${existing_terminal}")"
fi

log() { printf '%s  mt5-bridge: %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }
die() { log "ERROR: $*"; exit 1; }

# ---------------------------------------------------------------- display --
log "starting virtual display"
Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp &
sleep 2

if [ "${ENABLE_VNC:-0}" = "1" ]; then
  # Escape hatch: some brokers pop a dialog on first login, and a few require
  # confirming the terminal by hand once. Connect to :5900 to deal with it.
  log "starting VNC on 5900 (ENABLE_VNC=1)"
  x11vnc -display :99 -forever -shared -nopw -quiet -bg >/dev/null 2>&1 || \
    log "x11vnc is not available in this image"
fi

# ------------------------------------------------------------------- wine --
if [ ! -d "${WINEPREFIX}/drive_c" ]; then
  log "creating the Wine prefix (first boot)"
  wineboot --init >/dev/null 2>&1
  wineserver -w
fi

# The /wine volume outlives the image, so a prefix built by one Wine version
# gets handed to the next one on upgrade. Wine expects to be told about that:
# without an update pass the prefix keeps the old built-in DLLs and registry,
# and the failures that causes are silent and strange. Cheap when nothing
# changed, so it runs whenever the recorded version does not match.
wine_version="$(wine --version 2>/dev/null || echo unknown)"
version_stamp="${WINEPREFIX}/.tradezulu-wine-version"
if [ "$(cat "${version_stamp}" 2>/dev/null)" != "${wine_version}" ]; then
  if [ -f "${version_stamp}" ]; then
    log "Wine changed to ${wine_version}; updating the prefix"
  fi
  wineboot --update >/dev/null 2>&1 || true
  wineserver -w
  printf '%s' "${wine_version}" > "${version_stamp}" 2>/dev/null || true
fi

# Current MetaTrader builds expect Windows 10. Wine still reports 7 by default,
# and the terminal starts either way -- it just never opens its IPC pipe, which
# is a failure with no error attached to it.
wine reg add 'HKEY_CURRENT_USER\Software\Wine' /v Version /t REG_SZ /d win10 /f \
  >/dev/null 2>&1 || true

# Without this, a crashing Windows process opens winedbg and hangs forever
# instead of dying — which would leave the container "up" but wedged, and
# stop restart:unless-stopped from ever kicking in.
wine reg add 'HKEY_CURRENT_USER\Software\Wine\WineDbg' \
  /v ShowCrashDialog /t REG_DWORD /d 0 /f >/dev/null 2>&1 || true

# ----------------------------------------------------------------- python --
# The embeddable zip is used rather than the full installer: the installer is
# an MSI wrapper that frequently fails under Wine, while the zip is just files.
if [ ! -f "${WINE_PYTHON}" ]; then
  # A *real* install, not the embeddable zip. The embeddable build has no
  # registry entries, no site machinery and its own ._pth path rules, and the
  # MetaTrader5 package's IPC layer does not come up under it -- the terminal
  # runs and mt5.initialize() simply returns "IPC send failed" with nothing
  # else to go on. Every working setup in the wild uses the full installer.
  log "installing Windows Python ${PYTHON_VERSION} (full installer)"
  curl -fsSL -o /tmp/python-setup.exe "${PYTHON_EXE_URL}" || die "could not download Python"
  timeout "${PYTHON_INSTALL_TIMEOUT:-600}" wine /tmp/python-setup.exe /quiet \
    InstallAllUsers=1 PrependPath=1 Include_test=0 "TargetDir=${PYTHON_DIR_WIN}" \
    >/tmp/python-setup.log 2>&1 || true
  wineserver -w
  rm -f /tmp/python-setup.exe

  if [ ! -f "${WINE_PYTHON_UNIX}" ]; then
    log "the Python installer did not produce ${PYTHON_DIR_WIN}\\python.exe"
    [ -s /tmp/python-setup.log ] && tail -n 10 /tmp/python-setup.log | \
      while IFS= read -r line; do log "  ${line}"; done
    die "no Python to run the bridge with"
  fi

  log "upgrading pip"
  wine "${WINE_PYTHON}" -m pip install --upgrade --no-cache-dir pip >/dev/null 2>&1
  wineserver -w
fi

# Wine's Mono stand-in for .NET. The terminal installer and some broker builds
# expect it to exist; without it they fail in ways that look like a hang.
if [ ! -d "${WINEPREFIX}/drive_c/windows/mono" ] && [ -n "${WINE_MONO_URL}" ]; then
  log "installing wine-mono"
  curl -fsSL -o /tmp/mono.msi "${WINE_MONO_URL}" && \
    WINEDLLOVERRIDES=mscoree=d wine msiexec /i /tmp/mono.msi /qn >/dev/null 2>&1 || true
  wineserver -w
  rm -f /tmp/mono.msi
fi

if ! wine "${WINE_PYTHON}" -c "import MetaTrader5, numpy" >/dev/null 2>&1; then
  log "installing ${MT5_PACKAGE_SPEC} (with ${NUMPY_SPEC})"
  wine "${WINE_PYTHON}" -m pip install --no-cache-dir --no-warn-script-location \
    "${NUMPY_SPEC}" "${MT5_PACKAGE_SPEC}" \
    || die "could not install the MetaTrader5 package"
  wineserver -w
fi

# ------------------------------------------------------------- metatrader --
if [ ! -f "${MT5_TERMINAL}" ]; then
  log "downloading MetaTrader 5"
  log "  (MetaQuotes does not allow redistributing it, so it is fetched here"
  log "   rather than baked into the image)"
  curl -fsSL -o /tmp/mt5setup.exe "${MT5_SETUP_URL}" || die "could not download MetaTrader"

  # /auto installs without the wizard. It exits non-zero on some builds even
  # when it worked, so the file check below is what actually decides.
  #
  # The timeout matters: the installer fetches the terminal itself from
  # MetaQuotes, and on some Wine versions that stalls with no window and no
  # output. Without a bound the container would sit there for ever looking
  # healthy-ish, which is the worst possible failure mode.
  install_timeout="${MT5_INSTALL_TIMEOUT:-600}"
  log "running the installer (up to ${install_timeout}s)"
  timeout "${install_timeout}" wine /tmp/mt5setup.exe /auto >/tmp/mt5setup.log 2>&1 || true
  if [ ! -f "${MT5_TERMINAL}" ]; then
    log "installer did not finish within ${install_timeout}s; giving it a moment to settle"
    wineserver -k >/dev/null 2>&1 || true
    sleep 5
  fi
  wineserver -w
  rm -f /tmp/mt5setup.exe
fi

if [ ! -f "${MT5_TERMINAL}" ]; then
  log "MetaTrader 5 is not at ${MT5_TERMINAL}."
  log "Two ways forward:"
  log "  1. Your broker ships a custom build. Point MT5_SETUP_URL at their"
  log "     installer and recreate this container."
  log "  2. Install it once by hand into the /wine volume and set"
  log "     MT5_TERMINAL_PATH to where it landed."
  log "  3. The installer may simply have been slow. Raise MT5_INSTALL_TIMEOUT"
  log "     (currently ${install_timeout:-600}s) and restart the container; the"
  log "     /wine volume keeps everything that did succeed."
  if [ -s /tmp/mt5setup.log ]; then
    log "installer output:"
    tail -n 15 /tmp/mt5setup.log | while IFS= read -r line; do log "  ${line}"; done
  fi
  die "no terminal to run"
fi

# Catch a broken Python stack here rather than as a mystery crash later.
if ! wine "${WINE_PYTHON}" -c "import MetaTrader5, numpy" >/dev/null 2>&1; then
  log "the Windows Python cannot import MetaTrader5 and numpy under this Wine."
  log "If numpy is the problem, pin an older one with WINE_NUMPY_SPEC and"
  log "recreate the container. Current: ${NUMPY_SPEC}"
  die "python stack is not usable"
fi

# Deliberately *not* launching the terminal here.
#
# mt5.initialize(path=...) starts the terminal itself, and it starts it with
# /portable -- a different instance, with a different data directory, from one
# launched plainly. Starting our own first left two terminals competing, and
# the API talked to neither. So the probe below owns the terminal: it is both
# what starts it and what decides it is ready.
# Broker builds do not install to "MetaTrader 5" -- Vantage's lands in
# "Vantage Markets MT5 Terminal", and every broker picks its own name. So find
# the terminal rather than assuming where it is.
if [ -z "${MT5_TERMINAL_PATH:-}" ]; then
  found="$(find "${WINEPREFIX}/drive_c/Program Files" -maxdepth 2 -name terminal64.exe \
           2>/dev/null | head -n1)"
  if [ -n "${found}" ]; then
    # /wine/drive_c/X/terminal64.exe -> C:\X\terminal64.exe
    rest="${found#"${WINEPREFIX}/drive_c/"}"
    MT5_TERMINAL_PATH="C:\\$(printf '%s' "${rest}" | tr '/' '\\')"
    log "found the terminal at ${MT5_TERMINAL_PATH}"
  else
    MT5_TERMINAL_PATH="C:\\Program Files\\MetaTrader 5\\terminal64.exe"
  fi
fi
export MT5_TERMINAL_PATH

log "starting the terminal through the Python API"

# The Python package reaches the terminal over a named pipe, so it has to be
# genuinely running -- not merely spawned, and not a zombie.
# Readiness is *not* "a process exists". Wine shows the launcher command line
# immediately, so a process check passes about a second after launch and keeps
# passing while the terminal fails to come up -- which reports success for a
# terminal the Python API cannot reach, and hides the only fault that matters.
# So ask the API the actual question.
cat > /tmp/mt5_ready.py <<'PROBE'
import os
import sys

import MetaTrader5 as mt5

# A cold terminal recompiles its bundled MQL5 examples before it answers --
# two to three minutes on first run -- so the timeout has to outlast that or
# every attempt fails for a reason that has nothing to do with the setup.
path = os.environ.get("MT5_TERMINAL_PATH", "")
if mt5.initialize(path, timeout=300000) if path else mt5.initialize(timeout=300000):
    info = mt5.terminal_info()
    print(f"ready build={getattr(info, 'build', '?')}")
    sys.exit(0)
print(f"not ready {mt5.last_error()}")
sys.exit(1)
PROBE

terminal_alive() {
  wine "${WINE_PYTHON}" 'Z:\tmp\mt5_ready.py' 2>/dev/null | grep -q '^ready'
}

# Each probe starts a Windows Python under Wine, so it is expensive: a
# handful of patient attempts beats dozens of impatient ones.
# The probe itself waits up to five minutes, so a couple of attempts is
# plenty -- the first one does the launching and the waiting.
for _ in $(seq 1 3); do
  terminal_alive && break
  sleep 5
done

if ! terminal_alive; then
  log "the terminal never became reachable through the Python API."
  log "Wine too old for this MetaTrader build is the usual cause; the"
  log "terminal needs bcryptprimitives.dll, which arrived in Wine 9."
  log "Wine in this image: $(wine --version 2>/dev/null || echo unknown)"
  if [ -s /tmp/terminal.log ]; then
    log "last lines of the terminal log:"
    tail -n 20 /tmp/terminal.log | while IFS= read -r line; do log "  ${line}"; done
  else
    log "the terminal produced no output at all."
  fi
  log "Its last word on the matter:"
  log "  $(wine "${WINE_PYTHON}" 'Z:\\tmp\\mt5_ready.py' 2>&1 | tail -1)"
  log ""
  log "Ruled out already, so do not spend time on these again:"
  log "  * Docker networking. A Windows process under Wine connects to"
  log "    127.0.0.1 fine, and the terminal's own MCP port is listening."
  log "  * The terminal being unhealthy. It logs 'MCP started', compiles its"
  log "    131 bundled MQL5 files and runs LiveUpdate."
  log "  * Racing the first-run compile. That blocks the API for two to three"
  log "    minutes; the probe above already waits five."
  log "  * Wine's Windows version. It is set to 10, as MetaTrader expects."
  log "Still suspect: Wine's named-pipe support, which is what the Python"
  log "package uses, and the package version (working setups elsewhere pin an"
  log "old one against Python 3.9; this image has 3.11 and the current wheel)."
  die "the terminal is up but unreachable"
fi

log "terminal is up; giving it a moment to open its IPC pipe"
sleep 15


log "starting the bridge on port ${BRIDGE_PORT}"
exec wine "${WINE_PYTHON}" "Z:\\opt\\bridge\\bridge.py"
