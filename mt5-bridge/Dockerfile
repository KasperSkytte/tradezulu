# MetaTrader 5 running headless under Wine, with a small read-only HTTP bridge
# in front of it. This image is OPTIONAL: the TradeZuluSync Expert Advisor is
# the lighter and more reliable way to get deals into TradeZulu.
#
# The image is deliberately a two-stage affair at *runtime* rather than build
# time: MetaQuotes does not permit redistributing the terminal, so it is
# downloaded on first boot into the /wine volume and reused from then on.

FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    WINEPREFIX=/wine \
    WINEARCH=win64 \
    WINEDEBUG=-all \
    DISPLAY=:99 \
    PYTHONUNBUFFERED=1 \
    BRIDGE_PORT=8080

RUN dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        cabextract \
        curl \
        procps \
        wine \
        wine64 \
        winbind \
        xauth \
        xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY bridge.py /opt/bridge/bridge.py
RUN chmod +x /usr/local/bin/entrypoint.sh

VOLUME ["/wine"]
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=10s --start-period=10m --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${BRIDGE_PORT}/health" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
