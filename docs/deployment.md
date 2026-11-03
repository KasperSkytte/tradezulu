# Running TradeZulu on your own server

Everything runs in Docker:

| Container | What it is |
|---|---|
| `tradezulu` | The site: journal, copier and API, with SQLite in the `tradezulu-data` volume. |
| `tradezulu-orchestrator` | Keeps one terminal container per account running. The only thing with the Docker socket. |
| `tradezulu-terminal-<id>` | One per account: MetaTrader under Wine on a virtual screen, with the Expert Advisor in it. Created and removed by the orchestrator, not by compose. |

All of them are on one Docker network, `tradezulu`. Only the site publishes a
port, on `127.0.0.1`.

## Sizing

The site is tiny: idle it sits under 100 MB of RAM, and the heaviest thing it
does is recompute a few thousand trades, which takes well under a second.

The terminals are the greedy part. Budget per account roughly 500 MB of RAM and
a few hundred MB of disk for its volume (history and the broker's symbol
data). The images are big but shared: each Wine version is a base of about
4.5 GB, and each broker adds about 0.5 GB on top. Two brokers on the same Wine
are about 5.5 GB in all. They are nearly idle between ticks; a 4 vCPU / 8 GB
VM runs a handful of accounts comfortably.

## First run

```bash
git clone https://github.com/KasperSkytte/tradezulu.git /opt/tradezulu
cd /opt/tradezulu

./install.sh --brokers vantage,falcon
docker compose logs -f
```

`install.sh` writes `.env` with generated secrets, builds a terminal image for
each broker you name (a few minutes each: the broker's MetaTrader is
installed into the image and the Expert Advisor compiled), and starts the
stack. It is safe to re-run: the configuration is kept and existing images are
reused.

For a journal with no copying and no terminals, `./install.sh --no-terminals`.

`TZ_ADMIN_USER` and `TZ_ADMIN_PASSWORD` create the user on the **first** start
only. Afterwards, change it in Settings → Security. There is no registration
page and no way to create a second user from the UI — that is deliberate.

## nginx

The site binds to `127.0.0.1:8420`, so nothing reaches it except through your
proxy.

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

    # The terminal viewer is a WebSocket.
    location /api/terminal/ {
        proxy_pass         http://127.0.0.1:8420;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade           $http_upgrade;
        proxy_set_header   Connection        "upgrade";
        proxy_set_header   Host              $host;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 1h;
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

Everything worth keeping is in the `tradezulu-data` volume, plus `.env`, whose
`TZ_SECRET_KEY` is what decrypts the MetaTrader passwords stored in the
database. Back them up together. The terminals' volumes are not worth backing
up: they hold nothing the journal does not, and a terminal that has lost its
volume logs in again by itself.

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
git pull
./install.sh --brokers vantage,falcon
```

The schema is created on start-up and new columns are additive, so upgrades do
not need a migration step. Take a backup first anyway.

After a version that changes how trades are folded, run *Settings → MetaTrader 5
→ Rebuild trades from stored deals*. Because every raw deal is kept, this is
always available and never loses your notes.

### Terminal images

Terminal images are built here, never pulled: each one carries a broker's
MetaTrader, installed from that broker's own installer. Rebuild them when an
upgrade changes the Expert Advisor or anything under `terminal/`, or to pick up
a broker's new MetaTrader build:

```bash
terminal/build.sh vantage --refresh      # one broker, fresh install
./install.sh --brokers vantage,falcon --rebuild
```

The orchestrator always uses the image with the highest MetaTrader build for a
broker (and the newest of those). Terminals move to a new image at the weekly
restart, or at once when you press Restart for an account. Their volumes —
the saved login, history, symbol data — come along.

To go back, untag the newer image and press Restart; only an image tagged
`<broker>-<build>-wine<version>` is ever chosen, so the next one down is used:

```bash
docker rmi tradezulu-terminal:vantage-6296-wine11.0
docker tag tradezulu-terminal:vantage-6295-wine11.0 tradezulu-terminal:vantage
```

Old images are not removed automatically. Once every terminal has moved:

```bash
docker images tradezulu-terminal          # what is there
docker rmi tradezulu-terminal:vantage-6230-wine11.0
docker image prune -f
```

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

Terminal containers are created by the orchestrator rather than by compose, so
compose limits do not reach them.

## Health and logs

```bash
docker compose ps                              # the site and the orchestrator
docker compose logs -f tradezulu               # application log
docker compose logs -f orchestrator            # which terminals it starts, and why
docker ps --filter label=tz.role=terminal      # the terminals
docker logs -f tradezulu-terminal-3            # one terminal's supervisor
curl -s localhost:8420/api/health              # {"status":"ok", ...}
```

Each terminal's status is also on the Accounts page, along with its screen.
Set `TZ_LOG_LEVEL=DEBUG` for verbose output from the site.

## Running a second stack beside the first

Every name the stack uses can be changed in `.env`, so a throwaway test install
can run on the same machine against demo accounts without touching the real
one. In a separate checkout:

```bash
COMPOSE_PROJECT_NAME=tztest     # or compose takes the directory's name, which may be the real one's
TZ_PORT=8421
TZ_IMAGE_TAG=test               # so its builds do not replace the real images
TZ_CONTAINER_NAME=tztest-app
TZ_ORCHESTRATOR_NAME=tztest-orchestrator
TZ_NETWORK=tztest
TZ_STACK=tztest
```

```bash
./install.sh --brokers vantage
```

Terminal images are shared between the two, which is what you want. Remove it
with `./uninstall.sh --purge-data` from that checkout.

## Security notes

- One user, no registration, no password reset by email. Losing the password
  means recreating the database or resetting the hash by hand.
- Failed logins are throttled per client address: ten attempts, then a five
  minute lockout (`TZ_LOGIN_MAX_ATTEMPTS`, `TZ_LOGIN_LOCKOUT_SECONDS`).
- The session is a signed JWT in an httpOnly, SameSite=Lax cookie. Changing the
  password invalidates every other session immediately.
- The site runs as an unprivileged user and writes only to `/data`; so do the
  terminals, to their own volumes.
- **The orchestrator has the Docker socket, which is root on the host.** It is
  small, uses only Python's standard library, takes no input but TradeZulu's
  plan, and only acts on containers and volumes carrying its own stack's label.
  The site does not have the socket and cannot ask for anything but terminals
  for its own accounts.
- MetaTrader passwords are encrypted with AES-GCM under a key derived from
  `TZ_SECRET_KEY` and never returned to the browser. A terminal fetches its own
  account's login from the site with `TZ_INGEST_TOKEN` when it starts — so no
  password is in any container's environment or in `docker inspect` — hands it
  to MetaTrader, and deletes its copy once MetaTrader has logged in. Use the
  broker's **investor** password for an account you only journal, and it is
  read-only by construction.
- `TZ_INGEST_TOKEN` is what the terminals, their Expert Advisors and the
  orchestrator hold. With it they can report deals and positions and read the
  terminal plan, which includes the stored passwords; it cannot read your
  journal or change settings. Treat it like those passwords.
- Changing `TZ_SECRET_KEY` deliberately makes the stored passwords unreadable.
  TradeZulu detects this and asks for them again rather than carrying on.
- Terminals publish no ports. Their Expert Advisors only talk outwards, to the
  site on the Docker network.
- Each terminal's screen is served by a VNC server inside its container,
  reachable only on the Docker network, and the site relays it to the browser
  over the same authenticated session as the rest of the API.
- The screen is live in both directions: your keyboard and mouse reach the
  terminal, so a dialog it is stuck on can be answered. The viewer carries a
  red banner saying so for as long as it is open. Treat opening it on a live
  account the way you would treat sitting down at the terminal itself.
- One container per account is what makes that viewer safe to have at all: it
  shows one terminal because there is only one terminal on that screen. Note
  that accounts themselves are not owned by anybody yet — every login sees
  every account — so this is a boundary between *terminals*, not between users.
