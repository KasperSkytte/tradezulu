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
say "remove the compose stack                containers, images, network"
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
# Everything attached to a prefix, not only the terminal itself. Each launch
# goes through a chain of flatpak sandboxes wrapping a shell, plus a wineserver,
# and killing only terminal64.exe left that chain running -- which is why
# processes belonging to a removed prefix were still there after an uninstall
# said it was finished.
#
# The terminal and wineserver carry WINEPREFIX in their environment; the
# sandbox wrappers do not, because the script they run is what exports it, so
# for those it is in the command line instead. Both are matched, quoted exactly
# so that tz-1 never catches tz-11.
prefix_pids() {
  local prefix="$1" pid entry
  for entry in /proc/[0-9]*; do
    pid="${entry#/proc/}"
    [ -r "/proc/${pid}/environ" ] || continue
    if tr '\0' '\n' < "/proc/${pid}/environ" 2>/dev/null | grep -qx "WINEPREFIX=${prefix}"; then
      echo "${pid}"
    elif tr '\0' ' ' < "/proc/${pid}/cmdline" 2>/dev/null | grep -qF "WINEPREFIX=\"${prefix}\""; then
      echo "${pid}"
    fi
  done
}
signal_prefix() {
  local prefix="$1" sig="$2" pid found=0
  for pid in $(prefix_pids "${prefix}"); do
    found=$((found + 1))
    run kill "-${sig}" "${pid}" 2>/dev/null || true
  done
  [ "${found}" -gt 0 ] && say "  ${sig} to ${found} process(es) in $(basename "${prefix}")"
  return 0
}
for p in "${TZ_PREFIXES[@]:-}"; do [ -n "${p}" ] && signal_prefix "${p}" TERM; done
[ "${DRY_RUN}" -eq 0 ] && sleep 5
for p in "${TZ_PREFIXES[@]:-}"; do [ -n "${p}" ] && signal_prefix "${p}" KILL; done

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
# What the provisioner remembers about each terminal: which account it was for,
# when it was started, how many times it had to be restarted. Useless without
# the prefixes it describes.
run rm -rf "${BOTTLES}/.tz-state"

# The displays the terminals drew on, and the VNC servers on them. One per
# account from :77 upwards, and only ever ours: the pattern is anchored so a
# desktop session on :0 or somebody else's :1 is never matched.
for n in $(seq 77 99); do
  if pgrep -f "x11vnc -display :${n}\b" >/dev/null 2>&1; then
    step "Stopping the viewer on :${n}"
    run pkill -f "x11vnc -display :${n}\b" || true
  fi
  if pgrep -f "Xvfb :${n}\b" >/dev/null 2>&1; then
    step "Stopping the virtual display :${n}"
    run pkill -f "Xvfb :${n}\b" || true
  fi
done

# --- the site ----------------------------------------------------------------

step "Removing the compose stack"
if [ -f "${HERE}/docker-compose.yml" ] && command -v docker >/dev/null 2>&1; then
  # Only reach for sudo if the daemon will not talk to us directly. Being in the
  # docker group is the common case, and prefixing sudo anyway turns every
  # command below into a password prompt -- or, for the ones whose output is
  # read rather than shown, into a silent no-op that reports nothing to do.
  DOCKER=(docker)
  if ! docker info >/dev/null 2>&1 && [ -n "${SUDO}" ]; then
    DOCKER=("${SUDO}" docker)
  fi
  COMPOSE=("${DOCKER[@]}" compose -f "${HERE}/docker-compose.yml")

  # --remove-orphans matters here more than usual: services have been taken out
  # of this compose file over time (the MetaTrader-in-Docker attempt, and the
  # bridge that went with it). Without it, `down` removes only what the file
  # still describes and leaves the containers those services created running.
  if [ "${PURGE_DATA}" -eq 1 ]; then
    run "${COMPOSE[@]}" down --volumes --rmi all --remove-orphans || true
    [ "${DRY_RUN}" -eq 1 ] || say "containers, images, network and the data volume removed"
  else
    run "${COMPOSE[@]}" down --rmi all --remove-orphans || true
    [ "${DRY_RUN}" -eq 1 ] || say "containers, images and network removed; the data volume is kept"
  fi

  # `down` only knows what the compose file says today. Anything still carrying
  # this project's label afterwards came from a layout the file no longer
  # describes -- a renamed service, a volume from an older revision -- and would
  # otherwise sit there for good. The label is what makes this safe: a container
  # you started yourself does not have it and is never in scope.
  PROJECT="$(basename "${HERE}")"
  FILTER="label=com.docker.compose.project=${PROJECT}"
  sweep() { "${DOCKER[@]}" "$@" 2>/dev/null || true; }

  if [ "${DRY_RUN}" -eq 1 ]; then
    say "would then remove anything still labelled ${PROJECT}:"
    say "  containers  $(sweep ps -a --filter "${FILTER}" --format '{{.Names}}' | tr '\n' ' ')"
    say "  networks    $(sweep network ls --filter "${FILTER}" --format '{{.Name}}' | tr '\n' ' ')"
    if [ "${PURGE_DATA}" -eq 1 ]; then
      say "  volumes     $(sweep volume ls -q --filter "${FILTER}" | tr '\n' ' ')"
    fi
  else
    leftovers="$(sweep ps -aq --filter "${FILTER}")"
    if [ -n "${leftovers}" ]; then
      say "removing $(printf '%s\n' "${leftovers}" | wc -l) container(s) from an older layout"
      # shellcheck disable=SC2086
      sweep rm -f ${leftovers} >/dev/null
    fi

    if [ "${PURGE_DATA}" -eq 1 ]; then
      stale="$(sweep volume ls -q --filter "${FILTER}")"
      if [ -n "${stale}" ]; then
        say "removing $(printf '%s\n' "${stale}" | wc -l) volume(s) from an older layout"
        # shellcheck disable=SC2086
        sweep volume rm ${stale} >/dev/null
      fi
    fi

    nets="$(sweep network ls -q --filter "${FILTER}")"
    if [ -n "${nets}" ]; then
      # shellcheck disable=SC2086
      sweep network rm ${nets} >/dev/null
      say "network removed"
    fi
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
    say "left in place: ${BOTTLES}"
  else
    run rm -rf "${SODA_DIR}"
    say "removed the Soda Wine build"
    if command -v flatpak >/dev/null 2>&1; then
      # --delete-data, or the flatpak goes and its ~/.var/app tree stays: a
      # near-empty directory nobody can account for afterwards, which is what
      # "uninstalled" is not supposed to leave behind. Only reached when no
      # bottle but ours was found, so there is nothing in it to lose.
      run ${SUDO} flatpak uninstall -y --noninteractive --delete-data \
        com.usebottles.bottles || true
      say "removed the Bottles runtime"
    fi
    # Whatever the flatpak did not take with it. The runners are large and are
    # ours by construction: nothing else put a Wine build in this tree.
    APPDATA="${RUN_HOME}/.var/app/com.usebottles.bottles"
    if [ -d "${APPDATA}" ]; then
      run rm -rf "${APPDATA}"
      say "removed ${APPDATA}"
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
# Said plainly rather than left to be discovered: without --purge-wine the
# Bottles tree stays, and finding it afterwards reads like the uninstall did
# not finish. It is the Wine runtime, it is expensive to rebuild, and it may
# not be ours alone.
if [ "${DRY_RUN}" -eq 0 ] && [ "${PURGE_WINE}" -eq 0 ] && [ -d "${BOTTLES}" ]; then
  say "kept: ${BOTTLES}"
  say "      the Wine runtime, minus TradeZulu's prefixes. --all removes it too."
fi
if [ "${DRY_RUN}" -eq 1 ]; then
  say "This was a dry run. Nothing changed."
elif [ "${PURGE_DATA}" -eq 1 ]; then
  say "TradeZulu and its data are gone."
else
  say "TradeZulu is uninstalled. Your journal is still here:"
  say "  ${HERE}/.env         the key that decrypts it"
  say "  docker volume       $(basename "${HERE}")_tradezulu-data"
  say "Run ./install.sh to bring it back."
fi
