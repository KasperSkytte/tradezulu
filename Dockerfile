# TradeZulu — one container: FastAPI serves both the API and the built SPA,
# with SQLite on a volume. No database server, no reverse proxy inside.

# --- stage 1: build the frontend ------------------------------------------
# Pinned to the *build* platform: the output is platform-independent
# JavaScript, so a multi-arch release does not need to run Vite and its Rust
# native modules under QEMU emulation.
FROM --platform=$BUILDPLATFORM node:24-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build


# --- stage 2: runtime ------------------------------------------------------
FROM python:3.12-slim AS runtime

ARG VERSION=0.0.0
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ_VERSION=${VERSION} \
    TZ_DATA_DIR=/data \
    TZ_DATABASE_URL=sqlite:////data/tradezulu.db \
    TZ_STATIC_DIR=/app/static \
    PORT=8420

RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY --from=frontend /build/dist ./static
COPY mt5/ ./mt5/
# The broker list is shared: the provisioner reads it from agent/ on the host,
# and the web interface serves it from here so the account form can offer the
# same brokers and servers.
COPY agent/brokers.json ./brokers.json
# Read at runtime when TZ_VERSION was not passed in, so an image built without
# the build arg still reports the release it was cut from rather than 0.0.0.
COPY version.txt ./version.txt

# Run unprivileged. /data is a volume, so its ownership is fixed at start-up
# by the entrypoint rather than baked into the image.
RUN useradd --system --uid 10001 --create-home --home-dir /home/tradezulu tradezulu && \
    mkdir -p /data && chown -R tradezulu:tradezulu /data /app

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

VOLUME ["/data"]
EXPOSE 8420

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/health" || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["serve"]
