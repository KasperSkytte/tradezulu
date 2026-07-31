#!/usr/bin/env bash
# Look at the terminals TradeZulu is running.
#
# They live on a virtual display so they never appear on anyone's screen, which
# is right until something goes wrong and you need to see what MetaTrader is
# actually showing -- a login that failed, a dialog waiting for an answer, or an
# Expert Advisor that never attached.
#
#   ./tz-view.sh list             # which terminals are up, and their windows
#   ./tz-view.sh shot             # a PNG of the whole display
#   ./tz-view.sh shot 22609000    # just that account's window
#   ./tz-view.sh watch            # a live view over VNC, with the SSH command
#
# The display is :77 unless TZ_DISPLAY says otherwise, matching the
# provisioner. Nothing here changes anything -- it only reads the screen -- so
# it is safe to run against terminals that are trading.
#
set -euo pipefail

DISPLAY_ID="${TZ_DISPLAY:-:77}"
PORT="${TZ_VNC_PORT:-5977}"
OUT_DIR="${TZ_SHOT_DIR:-${TMPDIR:-/tmp}}"

# USER is not set under systemd, cron or docker exec, and this runs under all
# three. It is only ever used to spell out a command to copy and paste.
WHO="${USER:-$(id -un)}"
HOSTNAME_FQDN="$(hostname -f 2>/dev/null || hostname)"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

need() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is not installed. ${2:-apt install $1}"
}

# Everything below reads the display, so fail early and clearly if there is not
# one -- "no windows found" would otherwise look like "no terminals running".
check_display() {
  need xdotool
  if [ "${DISPLAY_ID#:}" != "${DISPLAY_ID}" ] \
     && [ ! -e "/tmp/.X11-unix/X${DISPLAY_ID#:}" ]; then
    die "no display at ${DISPLAY_ID}. Is the provisioner running? (systemctl status tradezulu-agent)"
  fi
  DISPLAY="${DISPLAY_ID}" xdotool getdisplaygeometry >/dev/null 2>&1 \
    || die "cannot read ${DISPLAY_ID}. If it belongs to another user, run this as them."
}

# MetaTrader puts the account number and server in the title bar, which is the
# only thing tying a window to an account -- Wine reports every terminal under
# the same executable path, so the process list cannot say which is which.
windows() {
  DISPLAY="${DISPLAY_ID}" xdotool search --name '.' 2>/dev/null || true
}

cmd_list() {
  check_display
  say "display ${DISPLAY_ID} ($(DISPLAY="${DISPLAY_ID}" xdotool getdisplaygeometry | tr ' ' 'x'))"
  say ""

  local found=0 id name
  for id in $(windows); do
    name="$(DISPLAY="${DISPLAY_ID}" xdotool getwindowname "$id" 2>/dev/null || true)"
    # Only real terminal windows: the root and various helpers have no title.
    case "${name}" in
      ''|'openbox'|'Desktop') continue ;;
    esac
    found=1
    printf '  %-12s %s\n' "$id" "$name"
  done
  [ "${found}" -eq 1 ] || say "  no terminal windows yet."

  say ""
  say "terminals running, by prefix:"
  local pid prefix any=0
  for pid in $(pgrep -f 'terminal64\.exe' 2>/dev/null || true); do
    [ -r "/proc/${pid}/environ" ] || continue
    prefix="$(tr '\0' '\n' < "/proc/${pid}/environ" 2>/dev/null | sed -n 's/^WINEPREFIX=//p')"
    [ -n "${prefix}" ] || continue
    any=1
    printf '  pid %-8s %s\n' "$pid" "$(basename "${prefix}")"
  done
  [ "${any}" -eq 1 ] || say "  none."
}

cmd_shot() {
  check_display
  need import "apt install imagemagick"

  local match="${1:-}" target="root" label="display" id name
  if [ -n "${match}" ]; then
    for id in $(windows); do
      name="$(DISPLAY="${DISPLAY_ID}" xdotool getwindowname "$id" 2>/dev/null || true)"
      case "${name}" in
        *"${match}"*) target="$id"; label="${match}"; break ;;
      esac
    done
    [ "${target}" != "root" ] || die "no window matching '${match}'. Try: $0 list"
  fi

  local file
  file="${OUT_DIR}/tz-${label//[^A-Za-z0-9._-]/_}-$(date +%H%M%S).png"
  DISPLAY="${DISPLAY_ID}" import -window "${target}" "${file}"
  say "wrote ${file}"
  say "copy it back with:  scp ${WHO}@${HOSTNAME_FQDN}:${file} ."
}

cmd_watch() {
  check_display
  need x11vnc "apt install x11vnc"

  say "Serving ${DISPLAY_ID} on localhost:${PORT}."
  say ""
  say "From your own machine, in another shell:"
  say "  ssh -N -L ${PORT}:localhost:${PORT} ${WHO}@${HOSTNAME_FQDN}"
  say "then point a VNC viewer at localhost:${PORT}."
  say ""
  say "Ctrl-C here when you are done."
  say ""
  # -localhost so this is only reachable through the SSH tunnel: the display
  # holds logged-in trading terminals and x11vnc has no authentication worth
  # the name. -viewonly because nothing here should be clicking on them.
  exec x11vnc -display "${DISPLAY_ID}" -localhost -rfbport "${PORT}" \
    -viewonly -shared -forever -nopw -quiet
}

case "${1:-list}" in
  list)         cmd_list ;;
  shot)         shift; cmd_shot "${1:-}" ;;
  watch|vnc)    cmd_watch ;;
  -h|--help)    sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//' ;;
  *)            die "unknown command: $1 (try: list, shot, watch)" ;;
esac
