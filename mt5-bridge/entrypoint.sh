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
PYTHON_ZIP_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-embed-amd64.zip"
GET_PIP_URL="https://bootstrap.pypa.io/get-pip.py"
MT5_SETUP_URL="${MT5_SETUP_URL:-https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe}"

PYTHON_DIR="${WINEPREFIX}/drive_c/Python"
WINE_PYTHON="${PYTHON_DIR}/python.exe"
MT5_DIR="${WINEPREFIX}/drive_c/Program Files/MetaTrader 5"
MT5_TERMINAL="${MT5_DIR}/terminal64.exe"

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

# Without this, a crashing Windows process opens winedbg and hangs forever
# instead of dying — which would leave the container "up" but wedged, and
# stop restart:unless-stopped from ever kicking in.
wine reg add 'HKEY_CURRENT_USER\Software\Wine\WineDbg' \
  /v ShowCrashDialog /t REG_DWORD /d 0 /f >/dev/null 2>&1 || true

# ----------------------------------------------------------------- python --
# The embeddable zip is used rather than the full installer: the installer is
# an MSI wrapper that frequently fails under Wine, while the zip is just files.
if [ ! -f "${WINE_PYTHON}" ]; then
  log "installing Windows Python ${PYTHON_VERSION}"
  mkdir -p "${PYTHON_DIR}"
  curl -fsSL -o /tmp/python.zip "${PYTHON_ZIP_URL}" || die "could not download Python"
  busybox unzip -q -o /tmp/python.zip -d "${PYTHON_DIR}" 2>/dev/null || \
    unzip -q -o /tmp/python.zip -d "${PYTHON_DIR}" || die "could not unpack Python"
  rm -f /tmp/python.zip

  # The embeddable build disables site-packages by default; turn it back on so
  # pip can install into it.
  for pth in "${PYTHON_DIR}"/python*._pth; do
    [ -f "$pth" ] || continue
    sed -i 's/^#import site/import site/' "$pth"
    grep -q '^Lib\\site-packages' "$pth" || echo 'Lib\site-packages' >> "$pth"
  done

  log "bootstrapping pip"
  curl -fsSL -o "${PYTHON_DIR}/get-pip.py" "${GET_PIP_URL}" || die "could not download get-pip"
  wine "${WINE_PYTHON}" 'C:\Python\get-pip.py' --no-warn-script-location >/dev/null 2>&1
  wineserver -w
fi

if ! wine "${WINE_PYTHON}" -c "import MetaTrader5, numpy" >/dev/null 2>&1; then
  log "installing the MetaTrader5 python package (with ${NUMPY_SPEC})"
  wine "${WINE_PYTHON}" -m pip install --no-cache-dir --no-warn-script-location \
    "${NUMPY_SPEC}" MetaTrader5 \
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

log "launching the terminal"
# Keep the output: a terminal that dies on startup is otherwise completely
# silent, and the only symptom is an IPC timeout a minute later.
wine "${MT5_TERMINAL}" >/tmp/terminal.log 2>&1 &

# The Python package reaches the terminal over a named pipe, so it has to be
# genuinely running -- not merely spawned, and not a zombie.
terminal_alive() {
  pgrep -x terminal64.exe >/dev/null 2>&1 || return 1
  # A process that exited but has not been reaped is state Z and no use to us.
  [ "$(ps -o stat= -C terminal64.exe 2>/dev/null | tr -d ' ' | head -c1)" != "Z" ]
}

for _ in $(seq 1 45); do
  terminal_alive && break
  sleep 2
done

if ! terminal_alive; then
  log "the terminal started and exited immediately."
  log "This is usually Wine being too old for your MetaTrader build."
  log "Wine in this image: $(wine --version 2>/dev/null || echo unknown)"
  if [ -s /tmp/terminal.log ]; then
    log "last lines of the terminal log:"
    tail -n 20 /tmp/terminal.log | while IFS= read -r line; do log "  ${line}"; done
  else
    log "the terminal produced no output at all."
  fi
  die "terminal will not stay running"
fi

log "terminal is up; giving it a moment to open its IPC pipe"
sleep 15

export MT5_TERMINAL_PATH="${MT5_TERMINAL_PATH:-C:\\Program Files\\MetaTrader 5\\terminal64.exe}"

log "starting the bridge on port ${BRIDGE_PORT}"
exec wine "${WINE_PYTHON}" "Z:\\opt\\bridge\\bridge.py"
