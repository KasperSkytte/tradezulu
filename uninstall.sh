#!/usr/bin/env bash
# Undo what install.sh did.
#
# By default this removes the software and leaves your trades alone: the
# journal database, the .env that can decrypt it, and anything you had on this
# machine before. Data is only deleted if you ask for it, twice.
#
#   ./uninstall.sh                 # remove the software, keep the journal
#   ./uninstall.sh --dry-run       # print what would happen, change nothing
#   ./uninstall.sh --purge-data    # also delete the journal and its secrets
#   ./uninstall.sh --all           # everything, including Wine and packages
#   sudo ./uninstall.sh --user labrat   # if it was installed with --user
#
# --user must match what install.sh was given: the terminals live in that
# account's home, and looking in the wrong one finds nothing and reports
# success.
#
# What is *never* touched, whatever you pass: MetaTrader prefixes that
# TradeZulu did not create. Only bottles named tz-<account> and tz-template-*
# are ever removed. Anything else in Bottles is yours and is left alone.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="/etc/systemd/system/tradezulu-agent.service"
RUN_USER=""

PURGE_DATA=0
PURGE_WINE=0
PURGE_PACKAGES=0
DRY_RUN=0
ASSUME_YES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --purge-data)     PURGE_DATA=1; shift ;;
    --purge-wine)     PURGE_WINE=1; shift ;;
    --purge-packages) PURGE_PACKAGES=1; shift ;;
    --all)            PURGE_DATA=1; PURGE_WINE=1; PURGE_PACKAGES=1; shift ;;
    --user)           RUN_USER="$2"; shift 2 ;;
    --dry-run|-n)     DRY_RUN=1; shift ;;
    --yes|-y)         ASSUME_YES=1; shift ;;
    -h|--help)        sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
say()  { printf '    %s\n' "$*"; }
run()  {
  if [ "${DRY_RUN}" -eq 1 ]; then
    printf '    would run: %s\n' "$*"
  else
    "$@"
  fi
}

SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1; then
  SUDO="sudo"
fi

# Where the terminals live. The same rule as install.sh: one user's home holds
# all of it, and that user is whoever ran the script unless --user says
# otherwise. The service file records what was actually used, so prefer it over
# guessing -- an uninstall that looks in the wrong home finds nothing to do and
# cheerfully says it is finished.
if [ -z "${RUN_USER}" ] && [ -r "${SERVICE}" ]; then
  RUN_HOME="$(sed -n 's/^Environment=HOME=//p' "${SERVICE}" | head -1)"
  RUN_USER="$(sed -n 's/^User=//p' "${SERVICE}" | head -1)"
fi
if [ -n "${RUN_USER:-}" ] && [ "${RUN_USER}" != "$(id -un)" ]; then
  [ -n "${RUN_HOME:-}" ] || RUN_HOME="$(getent passwd "${RUN_USER}" | cut -d: -f6)"
  [ -n "${RUN_HOME}" ] || RUN_HOME="${HERE}/.home"
else
  RUN_HOME="${HOME}"
fi
BOTTLES="${RUN_HOME}/.var/app/com.usebottles.bottles/data/bottles"
# Glob rather than name it: Bottles installs this runner as "soda-9.0-1" and
# the release tarball unpacks as "soda-9.0-1-x86_64".
SODA_DIR="$(find "${BOTTLES}/runners" -maxdepth 1 -name 'soda-*' -type d 2>/dev/null | sort | tail -1)"

# --- what is actually here ---------------------------------------------------

# Only ever these two shapes. A plain tz* glob would match a bottle someone
# happened to name "tzsomething", and deleting a stranger's MetaTrader install
# is not a recoverable mistake.
mapfile -t TZ_PREFIXES < <(
  find "${BOTTLES}/bottles" -maxdepth 1 -mindepth 1 -type d \
    \( -name 'tz-template-*' -o -regex '.*/tz-[0-9]+' \) 2>/dev/null | sort
)
mapfile -t OTHER_PREFIXES < <(
  find "${BOTTLES}/bottles" -maxdepth 1 -mindepth 1 -type d 2>/dev/null \
    | grep -vE '/tz-(template-.*|[0-9]+)$' | sort
)

step "What this will do"
say "remove the provisioning service         $([ -e "${SERVICE}" ] && echo yes || echo '(not installed)')"
say "stop and delete TradeZulu's terminals   ${#TZ_PREFIXES[@]} prefix(es)"
for p in "${TZ_PREFIXES[@]:-}"; do [ -n "${p}" ] && say "    - $(basename "${p}")"; done
say "remove the container and its image      yes"
say "delete the journal database and .env    $([ "${PURGE_DATA}" -eq 1 ] && echo 'YES -- your trade history' || echo 'no (kept)')"
say "remove Wine/Bottles                     $([ "${PURGE_WINE}" -eq 1 ] && echo yes || echo 'no (kept)')"
say "remove apt packages                     $([ "${PURGE_PACKAGES}" -eq 1 ] && echo yes || echo 'no (kept)')"

if [ "${#OTHER_PREFIXES[@]}" -gt 0 ] && [ -n "${OTHER_PREFIXES[0]:-}" ]; then
  say ""
  say "left alone (not TradeZulu's):"
  for p in "${OTHER_PREFIXES[@]}"; do say "    - $(basename "${p}")"; done
fi

if [ "${DRY_RUN}" -eq 1 ]; then
  step "Dry run"
  say "nothing above has been done."
fi

if [ "${DRY_RUN}" -eq 0 ] && [ "${ASSUME_YES}" -eq 0 ]; then
  echo
  if [ "${PURGE_DATA}" -eq 1 ]; then
    printf 'This deletes your trade history and cannot be undone. Type DELETE to confirm: '
    read -r reply
    [ "${reply}" = "DELETE" ] || { echo "aborted"; exit 1; }
  else
    printf 'Continue? [y/N] '
    read -r reply
    case "${reply}" in [yY]*) ;; *) echo "aborted"; exit 1 ;; esac
  fi
fi

# --- the service -------------------------------------------------------------

step "Stopping the provisioner"
if [ -e "${SERVICE}" ]; then
  run ${SUDO} systemctl disable --now tradezulu-agent.service || true
  run ${SUDO} rm -f "${SERVICE}"
  run ${SUDO} systemctl daemon-reload
  say "removed"
else
  say "not installed"
fi

# --- terminals ---------------------------------------------------------------

step "Stopping terminals"
# Wine reports every terminal under the same Windows path, so the command line
# cannot say which prefix a process belongs to. WINEPREFIX in its environment
# can, and it is the only thing that reliably distinguishes ours from yours.
stop_prefix() {
  local prefix="$1" pid found=0
  for pid in $(pgrep -f 'terminal64\.exe' 2>/dev/null || true); do
    [ -r "/proc/${pid}/environ" ] || continue
    if tr '\0' '\n' < "/proc/${pid}/environ" 2>/dev/null | grep -qx "WINEPREFIX=${prefix}"; then
      found=1
      run kill -TERM "${pid}" 2>/dev/null || true
    fi
  done
  [ "${found}" -eq 1 ] && say "  stopped terminals in $(basename "${prefix}")"
  return 0
}
for p in "${TZ_PREFIXES[@]:-}"; do [ -n "${p}" ] && stop_prefix "${p}"; done
[ "${DRY_RUN}" -eq 0 ] && sleep 5
for p in "${TZ_PREFIXES[@]:-}"; do
  [ -n "${p}" ] || continue
  for pid in $(pgrep -f 'terminal64\.exe' 2>/dev/null || true); do
    [ -r "/proc/${pid}/environ" ] || continue
    tr '\0' '\n' < "/proc/${pid}/environ" 2>/dev/null | grep -qx "WINEPREFIX=${p}" \
      && run kill -KILL "${pid}" 2>/dev/null || true
  done
done

step "Removing TradeZulu's MetaTrader prefixes"
if [ "${#TZ_PREFIXES[@]}" -eq 0 ] || [ -z "${TZ_PREFIXES[0]:-}" ]; then
  say "none"
else
  for p in "${TZ_PREFIXES[@]}"; do
    run rm -rf "${p}"
    say "removed $(basename "${p}")"
  done
fi
run rm -f "${BOTTLES}/.tz-last-maintenance"

# The display the terminals drew on. Only ours -- :77 by default, and only if
# nothing else is using it.
if pgrep -f 'Xvfb :77' >/dev/null 2>&1; then
  step "Stopping the virtual display"
  run pkill -f 'Xvfb :77' || true
  say "stopped :77"
fi

# --- the site ----------------------------------------------------------------

step "Removing the container"
if [ -f "${HERE}/docker-compose.yml" ] && command -v docker >/dev/null 2>&1; then
  if [ "${PURGE_DATA}" -eq 1 ]; then
    run ${SUDO} docker compose -f "${HERE}/docker-compose.yml" down -v --rmi all || true
    say "container, image and data volume removed"
  else
    run ${SUDO} docker compose -f "${HERE}/docker-compose.yml" down --rmi all || true
    say "container and image removed; the data volume is kept"
  fi
else
  say "no compose file or no docker here"
fi

if [ "${PURGE_DATA}" -eq 1 ]; then
  step "Removing the journal and its secrets"
  # .env holds TZ_SECRET_KEY, without which the stored MetaTrader password in
  # any surviving database cannot be decrypted. It goes with the data, never
  # separately.
  run rm -f "${HERE}/.env"
  run rm -rf "${HERE}/data"
  say "database, uploads and .env removed"
else
  step "Keeping your journal"
  say "the data volume and ${HERE}/.env are untouched"
  say "re-running install.sh here picks up exactly where this left off"
fi

# --- optional: Wine ----------------------------------------------------------

if [ "${PURGE_WINE}" -eq 1 ]; then
  step "Removing Wine and Bottles"
  if [ "${#OTHER_PREFIXES[@]}" -gt 0 ] && [ -n "${OTHER_PREFIXES[0]:-}" ]; then
    say "NOT removing: ${#OTHER_PREFIXES[@]} other bottle(s) are still installed here"
    say "removing the runtime would break them. Delete them first if you mean it."
  else
    run rm -rf "${SODA_DIR}"
    say "removed the Soda Wine build"
    if command -v flatpak >/dev/null 2>&1; then
      run ${SUDO} flatpak uninstall -y --noninteractive com.usebottles.bottles || true
      say "removed the Bottles runtime"
    fi
  fi
fi

# --- optional: packages ------------------------------------------------------

if [ "${PURGE_PACKAGES}" -eq 1 ]; then
  step "Removing packages"
  # curl and git are deliberately not in this list: install.sh may have
  # installed them, but so might anything else, and removing them from under a
  # working system is a poor trade for a few megabytes.
  run ${SUDO} apt-get remove -y -qq xvfb xdotool x11-utils openbox || true
  say "removed xvfb, xdotool, x11-utils, openbox"
  say "flatpak and curl are left: too likely to be someone else's"
fi

step "Done"
if [ "${DRY_RUN}" -eq 1 ]; then
  say "This was a dry run. Nothing changed."
elif [ "${PURGE_DATA}" -eq 1 ]; then
  say "TradeZulu and its data are gone."
else
  say "TradeZulu is uninstalled. Your journal is still here:"
  say "  ${HERE}/.env         the key that decrypts it"
  say "  docker volume       tradezulu-data"
  say "Run ./install.sh to bring it back."
fi
