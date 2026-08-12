# Running TradeZulu on your own server

TradeZulu is one container holding one SQLite file. Its resource appetite is
tiny: idle it sits under 100 MB of RAM, and the heaviest thing it ever does is
recompute a few thousand trades, which takes well under a second. A 2 vCPU /
1 GB VM is comfortable.

## First run

```bash
git clone https://github.com/KasperSkytte/tradezulu.git /opt/tradezulu
cd /opt/tradezulu

./install.sh --brokers default,vantage
docker compose logs -f tradezulu
```

`install.sh` writes `.env` with generated secrets, starts the site, and sets up
MetaTrader on the host. It is safe to re-run: every step checks whether it is
already done.

For a journal with no copying and no terminals, `cp .env.example .env` and
`docker compose up -d` is the whole thing.

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

### Upgrading to per-terminal screens

The version that added **Inspect** on the accounts page gives every terminal an
X display of its own — `:78` for account 1, `:79` for account 2, and so on —
where before they all drew on `:77`. Two things follow, and both are handled
for you:

```bash
cd /opt/tradezulu
git pull
sudo ./install.sh          # names the packages it is about to add, x11vnc among them
docker compose build && docker compose up -d
sudo systemctl restart tradezulu-agent
```

`install.sh` is safe to re-run: it checks each command rather than asking dpkg,
installs only what is missing, and leaves your prefixes, templates and database
alone.

Terminals that were already running are still on the old shared display, and
nothing about them is unhealthy, so supervision would leave them there for
ever — with Inspect showing whichever of them happens to be on top. The
provisioner notices on its first pass after the upgrade, stops each one, and
the next cycle brings it back on its own screen. Expect every terminal to
restart once, a minute or two apart, and copying to pause for that minute.

Nothing needs cleaning up by hand. The old `:77` is left running if something
else is on it, the new displays are created as needed, and a terminal is only
ever moved once — the screen it started on is recorded from now on, so a
second upgrade does not repeat it.

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

The terminals are the greedy part, and they are not containers — each is a
MetaTrader running under Wine on the host, wanting roughly 500 MB of RAM and
about 1 GB of disk on top of its template. Budget for one per account plus a
template per broker; they are nearly idle between ticks.

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
- Terminals only ever talk outwards, to `127.0.0.1`. Nothing listens on their
  behalf, so there is no port to expose and none to secure.
- The exception is the terminal viewer, and it is a narrow one. Each screen is
  served by an x11vnc bound to the host end of the Docker bridge — reachable by
  the TradeZulu container and by nothing on your network — and the site relays
  it to the browser over the same authenticated session as the rest of the API.
  The servers run `-viewonly`, so a viewer cannot click on a live account.
- One screen per account is what makes that viewer safe to have at all: it
  shows one terminal because there is only one terminal on the display it is
  connected to. Note that accounts themselves are not owned by anybody yet —
  every login sees every account — so this is a boundary between *terminals*,
  not between users.
