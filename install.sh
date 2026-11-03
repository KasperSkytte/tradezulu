#!/usr/bin/env bash
# Set up TradeZulu on a server with Docker.
#
# Everything runs in containers: the site, an orchestrator, and one MetaTrader
# terminal container per account, each on an image built for its broker. This
# script writes the configuration, builds the terminal images you ask for and
# starts the stack. It needs nothing on the host but Docker.
#
# It is safe to run more than once: the configuration is kept, images that
# exist are reused, and the stack is brought up to date.
#
#   ./install.sh                          # site + the generic MetaQuotes terminal
#   ./install.sh --brokers vantage,falcon # the brokers you use (see brokers.json)
#   ./install.sh --brokers all
#   ./install.sh --rebuild                # rebuild terminal images, picking up
#                                         # each broker's current MetaTrader build
#   ./install.sh --no-terminals           # journal only, no copying
#   ./install.sh --ignore-host-install    # a second, test stack on a machine that
#                                         # still has the old host terminals
#
# To undo it, see ./uninstall.sh. Coming from a TradeZulu that ran its
# terminals on the host (Bottles/Soda and the tradezulu-agent service)? Run
# ./migrate-from-host.sh first.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BROKERS="default"
TERMINALS=1
REBUILD=0
IGNORE_HOST=0

usage() { sed -n '2,23p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    --brokers) BROKERS="$2"; shift 2 ;;
    --no-terminals) TERMINALS=0; shift ;;
    --rebuild) REBUILD=1; shift ;;
    --ignore-host-install) IGNORE_HOST=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
say()  { printf '    %s\n' "$*"; }
die()  { printf '\n\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

step "Checking Docker"
command -v docker >/dev/null 2>&1 || die \
  "Docker is not installed. See https://docs.docker.com/engine/install/ then re-run."
docker compose version >/dev/null 2>&1 || die \
  "The Docker Compose plugin is missing. Install docker-compose-plugin then re-run."
docker info >/dev/null 2>&1 || die \
  "Cannot talk to the Docker daemon. Add yourself to the docker group (and log in again), or run this with sudo."
say "$(docker --version)"

step "Checking for an older, host-based install"
# The old provisioner ran a terminal per account on the host. Left running
# beside the orchestrator, every account would get two terminals -- and two
# Expert Advisors on one master is every trade copied twice.
# --ignore-host-install is for a second stack with accounts of its own, where
# that cannot happen.
if [ "${IGNORE_HOST}" -eq 1 ]; then
  say "not checked (--ignore-host-install)"
elif [ -e /etc/systemd/system/tradezulu-agent.service ] \
   || systemctl is-active --quiet tradezulu-agent 2>/dev/null; then
  die "the tradezulu-agent service from a host-based install is still here.
       Run ./migrate-from-host.sh first; it removes the old terminals and keeps your journal."
else
  say "none"
fi

step "Configuration"
ENV_FILE="${HERE}/.env"
random() { head -c 48 /dev/urandom | base64 | tr -d '/+=\n' | head -c "$1"; }
if [ ! -f "${ENV_FILE}" ]; then
  # Generated rather than asked for, so there is no step where a weak password
  # gets typed in "just for now" and then stays.
  umask 077
  cat > "${ENV_FILE}" <<EOF
TZ_ADMIN_USER=admin
TZ_ADMIN_PASSWORD=$(random 20)
TZ_SECRET_KEY=$(random 64)
TZ_INGEST_TOKEN=$(random 40)
EOF
  say "wrote .env with generated credentials"
  say "sign in with:  admin  /  $(sed -n 's/^TZ_ADMIN_PASSWORD=//p' "${ENV_FILE}")"
else
  say "keeping the existing .env"
  # An install from before the terminals authenticated may not have one, and
  # the orchestrator will not start without it.
  if ! grep -q '^TZ_INGEST_TOKEN=.' "${ENV_FILE}"; then
    printf 'TZ_INGEST_TOKEN=%s\n' "$(random 40)" >> "${ENV_FILE}"
    say "added a TZ_INGEST_TOKEN"
  fi
fi
PORT="$(sed -n 's/^TZ_PORT=//p' "${ENV_FILE}" | tail -1)"
PORT="${PORT:-8420}"

if [ "${TERMINALS}" -eq 1 ]; then
  step "Terminal images"
  if [ "${BROKERS}" = "all" ]; then
    BROKERS="$(python3 -c 'import json,sys; print(",".join(k for k,v in json.load(open(sys.argv[1])).items() if isinstance(v,dict)))' "${HERE}/brokers.json")"
  fi
  IFS=',' read -ra WANTED <<< "${BROKERS}"
  for broker in "${WANTED[@]}"; do
    if [ "${REBUILD}" -eq 0 ] && docker image inspect "tradezulu-terminal:${broker}" >/dev/null 2>&1; then
      say "${broker}: $(docker image inspect -f '{{index .Config.Labels "tz.mt5.build"}}' "tradezulu-terminal:${broker}" | sed 's/^/MetaTrader build /'), already built"
      continue
    fi
    say "${broker}: building (a few minutes; MetaTrader is installed into the image)"
    if [ "${REBUILD}" -eq 1 ]; then
      "${HERE}/terminal/build.sh" "${broker}" --refresh
    else
      "${HERE}/terminal/build.sh" "${broker}"
    fi
  done
fi

step "Building and starting TradeZulu"
( cd "${HERE}" && docker compose up -d --build )
say "waiting for it to answer"
for _ in $(seq 1 60); do
  if curl -sf -o /dev/null "http://127.0.0.1:${PORT}/api/health" 2>/dev/null; then
    say "up at http://127.0.0.1:${PORT}"
    break
  fi
  sleep 2
done

step "Done"
say "Open http://127.0.0.1:${PORT} and sign in."
if [ "${TERMINALS}" -eq 1 ]; then
  say "Add your MetaTrader accounts under Accounts: each gets a terminal container,"
  say "logged in and reporting, within a minute or so."
  say ""
  say "  docker logs -f tradezulu-orchestrator     # what it is starting and why"
  say "  docker ps --filter label=tz.role=terminal  # the terminals"
  say "  ./install.sh --brokers <name>              # another broker's image"
else
  say "Journal only. Re-run with --brokers <name> to add trade copying."
fi
