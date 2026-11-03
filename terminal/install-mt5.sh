#!/bin/sh
# Install a broker's MetaTrader into the image's Wine prefix. Build time only.
#
# Leaves /opt/tz/mt5 pointing at the install and /opt/tz/mt5-build holding its
# build number, which build.sh puts in the image's tag.
set -eu

INSTALLER="$1"
PF="${WINEPREFIX}/drive_c/Program Files"

Xvfb :1 -ac -screen 0 1400x1000x24 >/dev/null 2>&1 &
sleep 2
openbox >/dev/null 2>&1 &

echo "downloading ${INSTALLER}"
curl -fsSL --retry 3 -o /tmp/setup.exe "${INSTALLER}"

echo "installing"
wine /tmp/setup.exe /auto >/dev/null 2>&1 &

terminal=""
for _ in $(seq 1 90); do
  terminal="$(find "${PF}" -maxdepth 2 -name terminal64.exe 2>/dev/null | head -1)"
  [ -n "${terminal}" ] && break
  # MetaTrader's anti-debugger check refuses some Wine builds with a small
  # modal box titled after the program, and then waits for ever.
  if xdotool search --name '\.exe$' getwindowname %@ 2>/dev/null | grep -q .; then
    echo "error: the installer was refused by MetaTrader's anti-debugger check" >&2
    echo "       on this Wine build. Pick another 'wine' for this broker in" >&2
    echo "       brokers.json." >&2
    exit 3
  fi
  sleep 10
done
[ -n "${terminal}" ] || { echo "error: the installer produced no terminal64.exe" >&2; exit 1; }

# The installer starts the terminal when it is done; give it time to finish
# writing its first config (servers.dat above all), then stop everything.
sleep 30
wineserver -k || true
sleep 2
rm -f /tmp/setup.exe

dir="$(dirname "${terminal}")"
# The first run's log describes this build machine, not any account.
rm -rf "${dir}/logs" "${dir}/MQL5/Logs"
ln -sfn "${dir}" /opt/tz/mt5

python3 - "${terminal}" > /opt/tz/mt5-build <<'PY'
import sys
data = open(sys.argv[1], "rb").read()
at = data.find("FileVersion".encode("utf-16le"))
fields = data[at:at + 80].decode("utf-16le", "ignore").split("\x00")
version = next(f for f in fields[1:] if f.strip())
print(version.strip().split(".")[-1])
PY
echo "installed $(basename "${dir}"), build $(cat /opt/tz/mt5-build)"
