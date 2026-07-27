# Running TradeZulu on your own server

TradeZulu is one container holding one SQLite file. Its resource appetite is
tiny: idle it sits under 100 MB of RAM, and the heaviest thing it ever does is
recompute a few thousand trades, which takes well under a second. A 2 vCPU /
1 GB VM is comfortable.

## First run

```bash
git clone https://github.com/<you>/tradezulu.git /opt/tradezulu
cd /opt/tradezulu

cp .env.example .env
openssl rand -base64 48   # -> TZ_SECRET_KEY
openssl rand -hex 24      # -> TZ_BRIDGE_TOKEN
$EDITOR .env              # also set TZ_ADMIN_USER and TZ_ADMIN_PASSWORD

docker compose --profile bridge up -d
docker compose logs -f tradezulu
```

Leave `--profile bridge` off if you plan to use the Expert Advisor instead of
account-details sync; the journal runs perfectly well on its own.

`TZ_ADMIN_USER` and `TZ_ADMIN_PASSWORD` create the user on the **first** start
only. Afterwards, change it in Settings → Security. There is no registration
page and no way to create a second user from the UI — that is deliberate.

## nginx

The container binds to `127.0.0.1:8420`, so nothing reaches it except through
your proxy.

```nginx
server {
    listen 80;
    server_name journal.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name journal.example.com;

    ssl_certificate     /etc/letsencrypt/live/journal.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/journal.example.com/privkey.pem;

    # MetaTrader HTML reports of a long history can be a few megabytes.
    client_max_body_size 25m;

    # A PWA needs its service worker served fresh, or updates never land.
    location = /sw.js {
        proxy_pass http://127.0.0.1:8420;
        add_header Cache-Control "no-cache, no-store, must-revalidate";
    }

    location / {
        proxy_pass         http://127.0.0.1:8420;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
```

Then set `TZ_COOKIE_SECURE=true` in `.env` and `docker compose up -d` again, so
the session cookie carries the `Secure` flag.

`X-Forwarded-For` matters: the login throttle counts failures per client
address, and without the header every attempt looks like it came from nginx.

## Installing it on your phone

Open the site in Chrome or Safari and use *Add to home screen*. It gets an icon,
opens full screen and keeps you signed in for `TZ_SESSION_DAYS`. It needs the
network — a journal that shows stale numbers would be worse than one that says
it is offline — so only the shell is cached.

A valid HTTPS certificate is required for install prompts to appear at all.

## Backups

Everything is in the `tradezulu-data` volume: one SQLite file plus its
write-ahead log.

```bash
# Consistent copy while the container keeps running
docker compose exec tradezulu \
  python -c "import sqlite3,os; \
    src=sqlite3.connect('/data/tradezulu.db'); \
    dst=sqlite3.connect('/data/backup.db'); \
    src.backup(dst); dst.close(); src.close()"

docker compose cp tradezulu:/data/backup.db ./tradezulu-$(date +%F).db
docker compose exec tradezulu rm /data/backup.db
```

As a cron job:

```cron
15 3 * * * cd /opt/tradezulu && docker compose exec -T tradezulu python -c "import sqlite3;s=sqlite3.connect('/data/tradezulu.db');d=sqlite3.connect('/data/backup.db');s.backup(d);d.close();s.close()" && docker compose cp tradezulu:/data/backup.db /backups/tradezulu-$(date +\%F).db
```

You can also export every trade as CSV from *Settings → MetaTrader 5 → Export
everything as CSV*, which is a decent human-readable safety net — though it
does not include the raw deals, so prefer the database copy.

## Upgrading

```bash
cd /opt/tradezulu
docker compose pull
docker compose up -d
```

The schema is created on start-up and new columns are additive, so upgrades do
not need a migration step. Take a backup first anyway.

After a version that changes how trades are folded, run *Settings → MetaTrader 5
→ Rebuild trades from stored deals*. Because every raw deal is kept, this is
always available and never loses your notes.

## Resource limits

Worth adding on a shared Proxmox host:

```yaml
services:
  tradezulu:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 512M
```

The bridge container is the greedy one — Wine plus a MetaTrader terminal wants
roughly 1.5–2 GB of RAM and a couple of GB of disk, though it is nearly idle
between syncs:

```yaml
  mt5-bridge:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
```

Its `mt5-wine` volume is a cache, not data: deleting it costs you another
first boot and nothing else.

## Health and logs

```bash
docker compose ps                       # healthcheck status
docker compose logs -f tradezulu        # application log
curl -s localhost:8420/api/health       # {"status":"ok", ...}
```

Set `TZ_LOG_LEVEL=DEBUG` for verbose output when something is misbehaving.

## Security notes

- One user, no registration, no password reset by email. Losing the password
  means recreating the database or resetting the hash by hand.
- Failed logins are throttled per client address: ten attempts, then a five
  minute lockout (`TZ_LOGIN_MAX_ATTEMPTS`, `TZ_LOGIN_LOCKOUT_SECONDS`).
- The session is a signed JWT in an httpOnly, SameSite=Lax cookie. Changing the
  password invalidates every other session immediately.
- `TZ_INGEST_TOKEN` is the only credential the Expert Advisor holds, and it can
  only add deals. It cannot read your journal or change settings.
- The container runs as an unprivileged user and writes only to `/data`.
- Your MetaTrader password, if you use account-details sync, is encrypted with
  AES-GCM under a key derived from `TZ_SECRET_KEY`, is never returned by any
  API, and travels only to the terminal container on the internal network. Use
  the broker's **investor** password and it is read-only by construction, so
  the terminal cannot place an order regardless.
- Changing `TZ_SECRET_KEY` deliberately makes that stored password unreadable.
  TradeZulu detects this and asks for it again rather than carrying on.
- The `mt5-bridge` container is never published to the network; only TradeZulu
  can reach it, and `TZ_BRIDGE_TOKEN` gates even that.
