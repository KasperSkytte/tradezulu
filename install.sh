#!/usr/bin/env bash
# Set up TradeZulu on a fresh server.
#
# TradeZulu itself is containerised and needs nothing from the host. Its
# MetaTrader terminals are not: MetaTrader runs reliably under a normal Wine
# install and did not run reliably in a container, so the terminals live beside
# the containers rather than inside them. This script sets up both halves and
# the small process that joins them.
#
# It is safe to run more than once. Every step checks whether it is already
# done, so a re-run after a failure picks up where it stopped rather than
# starting over.
#
#   ./install.sh                      # site + terminals for the generic build
#   ./install.sh --brokers default,vantage
#   ./install.sh --no-terminals       # journal only, no copying
#   sudo ./install.sh --user labrat   # owned and run by a service account
#
# Wine, the terminals and the provisioning service all belong to one user. That
# is whoever runs this script, unless --user names another -- which is what you
# want on a server, where nobody should be logging in as the account that holds
# a broker session.
#
# To undo all of this, see ./uninstall.sh
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SODA_URL="https://github.com/bottlesdevs/wine/releases/download/soda-9.0-1/soda-9.0-1-x86_64.tar.xz"
BROKERS="default"
TERMINALS=1
RUN_USER=""

while [ $# -gt 0 ]; do
  case "$1" in
    --brokers) BROKERS="$2"; shift 2 ;;
    --no-terminals) TERMINALS=0; shift ;;
    --user) RUN_USER="$2"; shift 2 ;;
    -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
say()  { printf '    %s\n' "$*"; }
die()  { printf '\n\033[31merror: %s\033[0m\n' "$*" >&2; exit 1; }

need_root() {
  if [ "$(id -u)" -eq 0 ]; then SUDO=""
  elif command -v sudo >/dev/null 2>&1; then SUDO="sudo"
  else die "this step needs root and sudo is not installed"
  fi
}

# --- who owns the terminals --------------------------------------------------
#
# Everything under Wine -- the runtime, the templates, the account prefixes --
# lives in one user's home and is found through $HOME. So there is exactly one
# question to settle up front: which user. Packages and systemd still need
# root; only the Wine side is done as this account.
#
# Without --user that is whoever ran the script, which is what you want
# interactively. With it, root can set the whole thing up to be owned and run
# by a service account that has no login of its own.
if [ -z "${RUN_USER}" ]; then
  RUN_USER="$(id -un)"
  RUN_HOME="${HOME}"
  run_as() { "$@"; }
else
  need_root
  id "${RUN_USER}" >/dev/null 2>&1 || die "no such user: ${RUN_USER}"
  RUN_HOME="$(getent passwd "${RUN_USER}" | cut -d: -f6)"
  # A service account often has no home, or has one only nominally: `daemon`
  # is listed at /usr/sbin, which exists and is emphatically not a home. Taking
  # it at face value would mean chowning a system directory to a service
  # account, so the passwd entry is trusted only when the account actually owns
  # what it points at. Otherwise Wine gets a directory beside the checkout,
  # created here, rather than one invented in /home or an edit to the account.
  if [ -n "${RUN_HOME}" ] && [ -d "${RUN_HOME}" ] \
     && [ "$(stat -c '%U' "${RUN_HOME}" 2>/dev/null)" = "${RUN_USER}" ]; then
    say "using ${RUN_USER}'s home: ${RUN_HOME}"
  else
    RUN_HOME="${HERE}/.home"
    say "${RUN_USER} has no home of its own; using ${RUN_HOME}"
    ${SUDO} mkdir -p "${RUN_HOME}"
    ${SUDO} chown -R "${RUN_USER}" "${RUN_HOME}"
  fi
  # Dropping privilege is not the same shape as gaining it. ${SUDO} is empty
  # when already root, so "${SUDO} -u user cmd" becomes "-u user cmd" and the
  # shell tries to run -u. Root drops with runuser instead, which is also the
  # only one of the two guaranteed to be installed on a minimal server.
  if [ "$(id -u)" -eq 0 ] && command -v runuser >/dev/null 2>&1; then
    run_as() {
      runuser -u "${RUN_USER}" -- \
        env "HOME=${RUN_HOME}" "XDG_RUNTIME_DIR=${RUN_HOME}/.run" "$@"
    }
  else
    run_as() {
      sudo -u "${RUN_USER}" \
        env "HOME=${RUN_HOME}" "XDG_RUNTIME_DIR=${RUN_HOME}/.run" "$@"
    }
  fi
  run_as mkdir -p "${RUN_HOME}/.run"
fi
BOTTLES="${RUN_HOME}/.var/app/com.usebottles.bottles/data/bottles"

# Not a fixed directory name. Bottles' own component manager installs this
# runner as "soda-9.0-1", but the release tarball unpacks as
# "soda-9.0-1-x86_64" -- so anything hardcoding either name works on one
# machine and fails on the next. Everything else here globs soda-*; so does
# this.
soda_dir() { find "${BOTTLES}/runners" -maxdepth 1 -name 'soda-*' -type d 2>/dev/null | sort | tail -1; }

# --- the site ----------------------------------------------------------------

step "Checking Docker"
command -v docker >/dev/null 2>&1 || die \
  "Docker is not installed. See https://docs.docker.com/engine/install/ then re-run."
docker compose version >/dev/null 2>&1 || die \
  "The Docker Compose plugin is missing. Install docker-compose-plugin then re-run."
say "$(docker --version)"

step "Configuration"
if [ ! -f "${HERE}/.env" ]; then
  # Generating the secrets rather than asking for them means there is no step
  # here where a weak password gets typed in "just for now" and then stays.
  cat > "${HERE}/.env" <<EOF
TZ_ADMIN_USER=admin
TZ_ADMIN_PASSWORD=$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | head -c 20)
TZ_SECRET_KEY=$(head -c 48 /dev/urandom | base64 | tr -d '/+=')
TZ_INGEST_TOKEN=$(head -c 32 /dev/urandom | base64 | tr -d '/+=')
EOF
  chmod 600 "${HERE}/.env"
  say "wrote .env with generated credentials"
  say "sign in with:  $(grep TZ_ADMIN_USER "${HERE}/.env" | cut -d= -f2)  /  $(grep TZ_ADMIN_PASSWORD "${HERE}/.env" | cut -d= -f2)"
else
  say "keeping the existing .env"
fi

step "Building and starting TradeZulu"
( cd "${HERE}" && docker compose up -d --build )
say "waiting for it to answer"
for _ in $(seq 1 60); do
  if curl -sf -o /dev/null http://127.0.0.1:8420/ 2>/dev/null; then
    say "up at http://127.0.0.1:8420"
    break
  fi
  sleep 2
done

if [ "${TERMINALS}" -eq 0 ]; then
  step "Done"
  say "Journal is running. Re-run without --no-terminals to add trade copying."
  exit 0
fi

# --- the terminals -----------------------------------------------------------

step "Installing what the terminals need"
need_root
MISSING=()
# Checked by the command each one provides, not by asking dpkg whether the
# package is installed. `dpkg -s` succeeds for a package that has been removed
# but not purged -- Status "deinstall ok config-files" -- which is exactly the
# state uninstall.sh leaves behind. Re-installing after an uninstall therefore
# skipped all four X packages and only said so much later, when building a
# template failed on a missing xwininfo.
# x11vnc serves each terminal's screen to the web interface. It used to be
# optional -- looking at a terminal meant an SSH tunnel and your own viewer --
# and is not any more: Inspect on the accounts page needs one running here.
for entry in flatpak:flatpak xvfb:Xvfb xdotool:xdotool x11-utils:xwininfo \
             openbox:openbox x11vnc:x11vnc curl:curl; do
  command -v "${entry#*:}" >/dev/null 2>&1 || MISSING+=("${entry%%:*}")
done
if [ ${#MISSING[@]} -gt 0 ]; then
  # Named before they are fetched, not after. This is the one step that puts
  # packages on somebody's server, and "installing: xvfb x11vnc" ahead of it is
  # the difference between a script that asks and a script that helps itself.
  say "installing: ${MISSING[*]}"
  ${SUDO} apt-get update -qq
  ${SUDO} apt-get install -y -qq "${MISSING[@]}"
else
  say "already present"
fi

step "Installing the Wine runtime"
# Bottles is used as a runtime rather than as an application. Its runner is
# built against the flatpak's libraries, and the same runner outside that
# sandbox loads MetaTrader but cannot talk to it -- the failure that made
# containerising the terminal impossible. Keeping the sandbox keeps it working.
if ! flatpak remotes | grep -q flathub; then
  ${SUDO} flatpak remote-add --if-not-exists flathub \
    https://dl.flathub.org/repo/flathub.flatpakrepo
fi
if flatpak info com.usebottles.bottles >/dev/null 2>&1; then
  say "Bottles runtime already installed"
else
  say "downloading Bottles (a few hundred MB)"
  flatpak install -y --noninteractive flathub com.usebottles.bottles
fi

step "Installing the Soda Wine build"
if [ -n "$(soda_dir)" ] && [ -x "$(soda_dir)/bin/wine" ]; then
  say "already installed"
else
  # Mainline Wine loads MetaTrader but its inter-process layer never answers.
  # Soda is Proton-derived and does not have that fault. This is the single
  # most important choice in the whole setup.
  run_as mkdir -p "${BOTTLES}/runners" "${BOTTLES}/bottles"
  TMP="$(mktemp -d)"
  say "downloading soda-9.0-1 (~62 MB)"
  curl -fL --retry 3 --max-time 900 -o "${TMP}/soda.tar.xz" "${SODA_URL}"
  # The download happens as root but the unpacking does not, and mktemp -d
  # makes a directory only root can read. Without this the tar is handed a
  # file the account cannot open.
  chmod 755 "${TMP}"; chmod 644 "${TMP}/soda.tar.xz"
  run_as tar -C "${BOTTLES}/runners" -xf "${TMP}/soda.tar.xz"
  rm -rf "${TMP}"
  SODA_DIR="$(soda_dir)"
  if [ -z "${SODA_DIR}" ] || [ ! -x "${SODA_DIR}/bin/wine" ]; then
    die "Soda did not unpack into ${BOTTLES}/runners"
  fi
  say "installed as $(basename "${SODA_DIR}")"
fi

step "Building terminal templates"
# One install per broker, copied per account from here on.
IFS=',' read -ra WANTED <<< "${BROKERS}"
for broker in "${WANTED[@]}"; do
  say "--- ${broker} ---"
  run_as "${HERE}/agent/make-template.sh" "${broker}"
  # The two permissions the Expert Advisor needs live encrypted in
  # MetaTrader's own config and can only be set through its dialog. Doing it
  # on the template means every account inherits them and nobody ever meets
  # this step.
  run_as "${HERE}/agent/set-permissions.sh" "${broker}" || say \
    "could not set permissions automatically for ${broker} -- run agent/set-permissions.sh ${broker}"
done

step "Installing the provisioning service"
# A system service that runs as the user who owns the terminals.
#
# Not a --user service: that needs a login session to talk to, so it cannot be
# installed by anything running unattended -- a configuration management tool,
# or a plain `sudo ./install.sh` -- which is exactly how a server gets set up.
# Running as this user rather than root matters too: the terminals were built
# under this HOME, and Wine will not find them under any other.
TOKEN="$(grep '^TZ_INGEST_TOKEN=' "${HERE}/.env" | cut -d= -f2-)"
need_root
# The service runs from here, so the account behind it has to be able to read
# it. A checkout made by root -- by a configuration management run, say -- is
# not readable by a service account by default.
if [ "${RUN_USER}" != "$(id -un)" ]; then
  ${SUDO} chown -R "${RUN_USER}" "${HERE}/agent" "${HERE}/mt5"
fi
${SUDO} tee /etc/systemd/system/tradezulu-agent.service >/dev/null <<EOF
[Unit]
Description=TradeZulu terminal provisioner
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
# flatpak wants a runtime directory, and a service account has no session to
# get one from. systemd makes this one and cleans it up; pointing at
# /run/user/<uid> instead would name something nothing ever creates.
RuntimeDirectory=tradezulu-agent
Environment=XDG_RUNTIME_DIR=/run/tradezulu-agent
Environment=HOME=${RUN_HOME}
Environment=TZ_URL=http://127.0.0.1:8420
Environment=TZ_INGEST_TOKEN=${TOKEN}
Environment=TZ_DISPLAY=:77
WorkingDirectory=${HERE}
ExecStart=/usr/bin/python3 ${HERE}/agent/tz_provision.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
${SUDO} systemctl daemon-reload
${SUDO} systemctl enable --now tradezulu-agent.service
say "running as ${RUN_USER}"

step "Done"
say "Open http://127.0.0.1:8420 and sign in."
say "Add your MetaTrader account under Accounts; a terminal appears for it"
say "within a minute or so. You should not have to touch this machine again."
say ""
say "  sudo journalctl -u tradezulu-agent -f    # watch provisioning"
say "  ./uninstall.sh --dry-run             # what removing it would do"
