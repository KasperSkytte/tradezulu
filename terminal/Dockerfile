# One MetaTrader terminal, for one broker, at one MetaTrader build.
#
# Built by terminal/build.sh, which reads the broker's installer and Wine
# version from agent/brokers.json and tags the result
#
#   tradezulu-terminal:<broker>-<mt5 build>-wine<wine version>
#
# MetaTrader is installed and the Expert Advisor compiled here, at build time,
# so a terminal that starts has nothing left to download or build -- and an
# installer or compiler that refuses this Wine fails the build, loudly, rather
# than a terminal on a screen nobody is watching.
#
# Build context: the repository root.

ARG UBUNTU=24.04

# --- Wine --------------------------------------------------------------------
FROM ubuntu:${UBUNTU} AS wine

ARG WINE_BRANCH=stable
ARG WINE_VERSION=11.0.0.0~noble-1
ENV DEBIAN_FRONTEND=noninteractive

RUN dpkg --add-architecture i386 \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg tini python3 \
      xvfb openbox x11vnc xdotool x11-utils imagemagick \
 && mkdir -pm755 /etc/apt/keyrings \
 && curl -fsSL https://dl.winehq.org/wine-builds/winehq.key | gpg --dearmor -o /etc/apt/keyrings/winehq.gpg \
 && echo "deb [signed-by=/etc/apt/keyrings/winehq.gpg] https://dl.winehq.org/wine-builds/ubuntu/ noble main" \
      > /etc/apt/sources.list.d/winehq.list \
 && apt-get update \
 && apt-get install -y --install-recommends \
      "winehq-${WINE_BRANCH}=${WINE_VERSION}" "wine-${WINE_BRANCH}=${WINE_VERSION}" \
      "wine-${WINE_BRANCH}-amd64=${WINE_VERSION}" "wine-${WINE_BRANCH}-i386=${WINE_VERSION}" \
 && rm -rf /var/lib/apt/lists/*

# Ubuntu's image already has an unprivileged uid 1000 ("ubuntu"); use it.
ENV WINEPREFIX=/opt/wine \
    WINEDEBUG=-all \
    WINEDLLOVERRIDES="mscoree,mshtml=" \
    DISPLAY=:1 \
    HOME=/home/ubuntu
RUN mkdir -p /opt/wine /opt/tz/ea && chown -R 1000:1000 /opt/wine /opt/tz
USER 1000
RUN xvfb-run -a sh -c 'wineboot -i && wineserver -w'

# --- the broker's MetaTrader -------------------------------------------------
FROM wine AS terminal

ARG BROKER
ARG INSTALLER
# Changed by build.sh --refresh, so the installer runs again and fetches the
# broker's current build instead of the cached one.
ARG REFRESH=0
COPY --chown=1000:1000 terminal/install-mt5.sh /opt/tz/
RUN echo "refresh ${REFRESH}" && /opt/tz/install-mt5.sh "${INSTALLER}"

COPY --chown=1000:1000 mt5/TradeZuluCopier.mq5 /opt/tz/ea/
COPY --chown=1000:1000 terminal/compile-ea.sh /opt/tz/
RUN /opt/tz/compile-ea.sh

COPY --chown=1000:1000 terminal/supervisor.py /opt/tz/

# A new volume takes the ownership of the directory it is mounted over, so this
# is what makes an account's volume writable by the terminal.
USER root
RUN mkdir -p /data && chown 1000:1000 /data
USER 1000

ARG MT5_BUILD=""
ARG WINE_LABEL=""
LABEL org.opencontainers.image.title="TradeZulu terminal" \
      tz.role="terminal" \
      tz.broker="${BROKER}" \
      tz.mt5.build="${MT5_BUILD}" \
      tz.wine="${WINE_LABEL}"

EXPOSE 5900
VOLUME ["/data"]
ENTRYPOINT ["tini", "--", "python3", "-u", "/opt/tz/supervisor.py"]
