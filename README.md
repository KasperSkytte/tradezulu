<div align="center">

# TradeZulu

**A private trading journal for MetaTrader 5.**
Syncs your deals, works out what you actually risked, and tells you which habits are costing you money.

</div>

---

TradeZulu is a self-hosted alternative to TradeZella and Edgewonk. It is a single
Docker container behind your own nginx, it stores everything in one SQLite file,
and it costs nothing to run — no accounts, no subscriptions, no third-party
service holding your trading history.

## What it does

- **Syncs from MetaTrader 5** — an Expert Advisor inside your terminal pushes
  every deal to the journal, or the server pulls them from an optional bridge
  container. HTML reports and CSV files import too.
- **Thinks in R, not just money** — risk is derived from the stop loss the
  broker recorded, so planned R, realised R and expectancy are real numbers
  rather than guesses. Anything the broker did not record you can fill in by
  hand, per trade.
- **Treats breakevens honestly** — a trade that closes within 0.1R of your entry
  was a wasted effort, not a win. Breakevens are counted, shown and kept out of
  the win rate. The threshold and the handling are both configurable.
- **Zulu Score** — one 0–100 number built from six weighted components (win
  rate, profit factor, average win/loss, drawdown, recovery factor and
  consistency), with the targets and weights under your control.
- **Full statistics** — profit factor, expectancy, payoff ratio, maximum
  drawdown, recovery factor, Sharpe, Sortino, Kelly, streaks, hold times and
  day statistics, all for whatever date range you pick.
- **Calendar** — a month grid with each day's P&L, trade count, win rate and R,
  plus weekly roll-ups and a note per day.
- **Reports** — the same statistics broken down by symbol, tag, setup, day of
  week, hour opened, hold time and R multiple. This is where "FOMO trade" turns
  into a number.
- **Journal** — notes, a setup name, a 1–5 rating and tags on every trade,
  with tags like *bad entry*, *overrisked*, *overtrading* and *FOMO trade*
  seeded on first run and fully editable.
- **Chart replay** — candles stored by the Expert Advisor are replayed with your
  real entry, exit, stop and target drawn on them; a free TradingView widget is
  one click away when you want the full drawing toolset.
- **Installable on your phone** — it is a PWA, so "Add to home screen" gives you
  an app icon and a full-screen layout.

## Screenshots

| Dashboard | Calendar |
|---|---|
| ![Dashboard](docs/screenshots/dashboard.png) | ![Calendar](docs/screenshots/calendar.png) |

| Trades | Trade detail |
|---|---|
| ![Trades](docs/screenshots/trades.png) | ![Trade detail](docs/screenshots/trade-detail.png) |

| Reports | On a phone |
|---|---|
| ![Reports](docs/screenshots/reports.png) | <img src="docs/screenshots/mobile.png" width="260" alt="TradeZulu on a phone"> |

## Quick start

```bash
git clone https://github.com/<you>/tradezulu.git
cd tradezulu

cp .env.example .env
# Generate the two secrets and put them in .env:
openssl rand -base64 48   # -> TZ_SECRET_KEY
openssl rand -hex 24      # -> TZ_INGEST_TOKEN
# Also set TZ_ADMIN_USER and TZ_ADMIN_PASSWORD.

docker compose up -d
```

Open <http://localhost:8420> and sign in. To look around before connecting
MetaTrader, start it once with generated trades:

```bash
docker compose run --rm -p 8420:8420 -e TZ_DEMO=1 tradezulu demo
```

The user is created from `TZ_ADMIN_USER` / `TZ_ADMIN_PASSWORD` on the **first**
start only. After that, change the password from Settings → Security.

## Connecting MetaTrader 5

The recommended route needs nothing exposed to the internet — the terminal
calls TradeZulu, not the other way round.

1. Copy [`mt5/TradeZuluSync.mq5`](mt5/TradeZuluSync.mq5) into `MQL5/Experts` in
   your terminal's data folder (*File → Open Data Folder*) and compile it in
   MetaEditor with **F7**.
2. In MetaTrader: *Tools → Options → Expert Advisors* → tick **Allow WebRequest
   for listed URL** and add your TradeZulu origin, e.g.
   `https://journal.example.com`.
3. Drag **TradeZuluSync** onto any chart. Set `ServerUrl` to
   `https://journal.example.com/api` and `ApiKey` to your `TZ_INGEST_TOKEN`.

It sends your whole history on the first run and only new deals after that. The
chart comment shows what it is doing.

Two other routes are available — a pull-based bridge container, and plain file
import — see **[docs/metatrader.md](docs/metatrader.md)**.

## Behind nginx

TradeZulu binds to `127.0.0.1:8420` by default, so put your usual reverse proxy
in front of it:

```nginx
server {
    listen 443 ssl http2;
    server_name journal.example.com;

    ssl_certificate     /etc/letsencrypt/live/journal.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/journal.example.com/privkey.pem;

    client_max_body_size 25m;   # MetaTrader HTML reports can be large

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

Then set `TZ_COOKIE_SECURE=true` in `.env` and restart, so the session cookie is
only ever sent over HTTPS. More, including backups, in
**[docs/deployment.md](docs/deployment.md)**.

## Configuration

Everything you might want to change day to day lives on the **Settings** page:
breakeven thresholds, how risk is assumed when the broker recorded no stop,
commission and swap handling, Sharpe inputs, Zulu Score weights and targets,
tags, timezone, currency, theme and chart preferences.

Only deployment-level settings live in `.env`:

| Variable | Default | What it does |
|---|---|---|
| `TZ_SECRET_KEY` | *(random)* | Signs the session cookie. Set it, or restarts log you out. |
| `TZ_ADMIN_USER` | `admin` | Username created on the first start. |
| `TZ_ADMIN_PASSWORD` | — | Password created on the first start. Required once. |
| `TZ_INGEST_TOKEN` | — | Shared key the Expert Advisor authenticates with. |
| `TZ_COOKIE_SECURE` | `false` | Set to `true` when served over HTTPS. |
| `TZ_SESSION_DAYS` | `30` | How long a login lasts. |
| `TZ_PORT` | `8420` | Host port the container publishes on. |
| `TZ_DATA_DIR` | `/data` | Where the SQLite database lives. |
| `TZ_DEMO` | unset | Generate example trades on an empty database. |
| `TZ_LOG_LEVEL` | `INFO` | `DEBUG` for more detail. |

## How the numbers are worked out

Short version: MetaTrader records *deals*, not trades. TradeZulu groups every
deal that shares a `position_id` into one trade, volume-weighting the entry and
exit prices, so scale-ins and partial exits come out as a single row that reads
the way you traded it.

Risk is `|entry − stop| × value-per-point × lots`. Realised R is net P&L divided
by that risk; planned R is the target distance over the stop distance. When the
broker recorded no stop, the Expert Advisor's remembered stop is used, then your
manual override, then the fallback you configured.

Every metric — including exactly how drawdown, Sharpe, consistency and the Zulu
Score are computed — is written out in **[docs/metrics.md](docs/metrics.md)**.

## Development

```bash
# Backend
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
TZ_SECRET_KEY=dev TZ_ADMIN_USER=dev TZ_ADMIN_PASSWORD=devpassword TZ_DEMO=1 \
  uvicorn app.main:app --reload --port 8420

# Frontend (proxies /api to the backend above)
cd frontend
npm install
npm run dev
```

```bash
cd backend && pytest        # 116 tests
cd backend && ruff check .
cd frontend && npm run build
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/);
release-please turns them into releases, a changelog and a published container
image.

## Layout

```
backend/     FastAPI application, SQLite models, statistics engine, tests
frontend/    React + Vite single-page app, built into the container
mt5/         TradeZuluSync.mq5 — the Expert Advisor that pushes deals
mt5-bridge/  Optional headless MetaTrader 5 under Wine, for pull-based sync
docker/      Container entrypoint
docs/        MetaTrader guide, metric definitions, deployment notes
```

## Licence

MIT — see [LICENSE](LICENSE).

TradeZulu is not affiliated with MetaQuotes, TradeZella, Edgewonk or TradingView.
