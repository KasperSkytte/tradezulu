#!/usr/bin/env bash
# Bring up a headless MetaTrader 5 under Wine and start the read-only bridge.
#
# First boot downloads the terminal and a Windows Python into /wine, which
# takes several minutes. Keep /wine on a volume and later starts are quick.
set -euo pipefail

PYTHON_VERSION="${WINE_PYTHON_VERSION:-3.11.9}"
PYTHON_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/python-${PYTHON_VERSION}-amd64.exe"
MT5_SETUP_URL="${MT5_SETUP_URL:-https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe}"

WINE_PYTHON="${WINEPREFIX}/drive_c/Python/python.exe"
MT5_TERMINAL="${WINEPREFIX}/drive_c/Program Files/MetaTrader 5/terminal64.exe"

log() { printf '%s  %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }

log "starting virtual display"
Xvfb :99 -screen 0 1280x1024x24 -nolisten tcp &
sleep 2

if [ ! -d "${WINEPREFIX}/drive_c" ]; then
  log "creating Wine prefix (first boot, this takes a while)"
  wineboot --init
  wineserver -w
fi

if [ ! -f "${WINE_PYTHON}" ]; then
  log "installing Windows Python ${PYTHON_VERSION} into the prefix"
  curl -fsSL -o /tmp/python-setup.exe "${PYTHON_URL}"
  wine /tmp/python-setup.exe /quiet InstallAllUsers=0 PrependPath=0 Include_test=0 \
       TargetDir='C:\Python'
  wineserver -w
  rm -f /tmp/python-setup.exe
fi

if ! wine "${WINE_PYTHON}" -c "import MetaTrader5" >/dev/null 2>&1; then
  log "installing the MetaTrader5 python package"
  wine "${WINE_PYTHON}" -m pip install --no-cache-dir --upgrade pip
  wine "${WINE_PYTHON}" -m pip install --no-cache-dir MetaTrader5
  wineserver -w
fi

if [ ! -f "${MT5_TERMINAL}" ]; then
  log "downloading MetaTrader 5 (not redistributable, so fetched at runtime)"
  curl -fsSL -o /tmp/mt5setup.exe "${MT5_SETUP_URL}"
  # /auto runs the installer without a wizard.
  wine /tmp/mt5setup.exe /auto || true
  wineserver -w
  rm -f /tmp/mt5setup.exe
fi

if [ ! -f "${MT5_TERMINAL}" ]; then
  log "ERROR: MetaTrader 5 is not installed at ${MT5_TERMINAL}."
  log "       Install it once by hand into the /wine volume, or set"
  log "       MT5_TERMINAL_PATH to wherever your broker's build lives."
  exit 1
fi

log "launching the terminal in portable mode"
wine "${MT5_TERMINAL}" /portable &
sleep 20

export MT5_TERMINAL_PATH="${MT5_TERMINAL_PATH:-C:\\Program Files\\MetaTrader 5\\terminal64.exe}"

log "starting the bridge on port ${BRIDGE_PORT}"
exec wine "${WINE_PYTHON}" "Z:\\opt\\bridge\\bridge.py"
