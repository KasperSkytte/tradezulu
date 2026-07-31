<div align="center">

# TradeZulu

**A trade copier and trading journal for MetaTrader 5, in one.**

Copy one account's trades to any number of others under your own risk rules,
and journal every one of them. Self-hosted, free, and yours.

</div>

![Dashboard](docs/screenshots/dashboard.png)

## Quick start

```bash
git clone https://github.com/KasperSkytte/tradezulu.git
cd tradezulu
./install.sh --brokers default,vantage
```

That sets up everything: the site in Docker, and MetaTrader on the host with a
terminal template per broker. It generates your `.env` and prints the login it
made. Open <http://localhost:8420>, sign in, add your account, and a terminal
is started and logged in for it within a minute. You install nothing by hand
and are never asked for a URL or a token.

Journal only, no copying or terminals:

```bash
cp .env.example .env      # set TZ_SECRET_KEY and an admin password
docker compose up -d
```

Everything lives in one SQLite file under `./data`.

The admin user is created on the **first** start only, so editing those
variables later has no effect — change the password in Settings, or from
outside if you are locked out:

```bash
docker compose exec tradezulu set-password --username you --password 'a new one'
docker compose exec tradezulu list-users            # if you forgot the name
```

**Just want a look first?** This fills a throwaway database with example trades:

```bash
docker compose run --rm --service-ports -e TZ_DEMO=1 tradezulu demo
```

## What it does

**Copier** — one master account, any number of slaves, any broker.

- Sizing that fits each account: fixed lots, a multiplier, the balance or
  equity ratio, or a fixed percentage of the slave's equity risked against the
  master's stop. Lots round *down* to the broker's step, and a size under the
  minimum is refused rather than rounded up into more risk than you allowed.
- Per-account limits: max risk per trade, max lot, max open positions, max in
  one direction, max per symbol, max total lots.
- Account guards: equity stop by amount or percentage below peak, daily
  drawdown from the day's opening equity, daily profit target. When one trips,
  the account flattens and stops copying.
- Prop-firm rules: bank a winner at a money amount or an R multiple, and cap
  how much of total profit a single day may be.
- Stop and target moves follow through to every slave; a close is a close
  everywhere. Broker symbol differences (`EURUSD`, `EURUSD.r`, `FX_EURUSD`)
  are resolved per account, never guessed.
- Every slave starts disabled and in dry-run, recording what it *would* have
  done. You arm them one at a time.

**Journal** — what actually happened, and what it cost you.

- Thinks in R. Risk comes from the broker's recorded stop, so planned R,
  realised R and expectancy are real numbers.
- Breakevens counted honestly — a trade that closed at your entry was wasted
  effort, not a win, and stays out of the win rate.
- Zulu Score: one 0–100 number from six weighted components you control.
- Full statistics, a P&L calendar, and reports by symbol, tag, setup, weekday,
  hour, hold time and R multiple.
- Notes, ratings and tags per trade, so "FOMO trade" becomes a currency figure.
- Chart replay with your real entry, exit, stop and target drawn on it.
- Stats per account or all of them together, with equity curves each.
- Installable on a phone as a PWA.

| Calendar                                   | Trades                                 | Reports                                  |
|--------------------------------------------|----------------------------------------|------------------------------------------|
| ![Calendar](docs/screenshots/calendar.png) | ![Trades](docs/screenshots/trades.png) | ![Reports](docs/screenshots/reports.png) |

## Connect MetaTrader 5

**Settings → MetaTrader 5**, three fields:

| Field | Example |
|---|---|
| Trade server | `ICMarketsSC-Live12` |
| Account number | `5000123` |
| Investor password | the read-only one your broker issued |

That is the whole setup. A MetaTrader terminal is created for the account,
logged in, and given an Expert Advisor that reports back — automatically,
within a minute or so. Nothing to install, no files to copy, no URL to type.

For the journal, use the **investor password**: it is read-only, so TradeZulu
cannot trade your account even by accident. Copying to a slave account does
need that account's full password, which is why slaves stay in dry-run until
you arm them.

Terminals are restarted every Sunday so MetaTrader's updates install during a
quiet hour, rather than a broker's new build stopping a terminal mid-week with
a dialog nobody is there to answer.

MetaTrader runs on the host rather than in a container, which is not for want
of trying — [docs/metatrader.md](docs/metatrader.md) covers how it is put
together and what was ruled out.

## Known issues

Open problems are tracked as
[GitHub issues](https://github.com/KasperSkytte/tradezulu/issues) — worth a look
before reporting something. The ones to know about today:

- **Chart replay is empty.** No candles are uploaded yet
  ([#6](https://github.com/KasperSkytte/tradezulu/issues/6)). Set
  **Settings → Charts → TradingView** in the meantime.
- **A stop attached after entry** is lost if the terminal restarts before the
  trade closes, so that trade has no R
  ([#7](https://github.com/KasperSkytte/tradezulu/issues/7)). Stops set with the
  order are unaffected.
- **Copying to a slave has not been run against a live account**
  ([#10](https://github.com/KasperSkytte/tradezulu/issues/10)). The rules are
  well covered by tests, but arm your first slave on a demo.

## Behind a reverse proxy

TradeZulu binds to `127.0.0.1:8420`, so put nginx in front:

```nginx
server {
    listen 443 ssl;
    server_name trades.example.com;

    ssl_certificate     /etc/letsencrypt/live/trades.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/trades.example.com/privkey.pem;

    client_max_body_size 25m;

    location / {
        proxy_pass       http://127.0.0.1:8420;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Set `TZ_COOKIE_SECURE=true` in `.env` so the session cookie is HTTPS-only.
Backups and more in [docs/deployment.md](docs/deployment.md).

## Configuration

Day-to-day settings — risk defaults, breakeven handling, Zulu Score weights,
tags, timezone, currency, theme — are all on the **Settings** page.

`.env` holds only deployment settings:

| Variable | Default | What it does |
|---|---|---|
| `TZ_SECRET_KEY` | *(random)* | Signs the session cookie. Set it, or restarts log you out. |
| `TZ_ADMIN_USER` / `TZ_ADMIN_PASSWORD` | `admin` / — | Created on the first start. |
| `TZ_INGEST_TOKEN` | *(generated)* | Key the terminals authenticate with. |
| `TZ_COOKIE_SECURE` | `false` | `true` when served over HTTPS. |
| `TZ_PORT` | `8420` | Host port. |
| `TZ_DEMO` | unset | Generate example trades on an empty database. |

The full list is in [.env.example](.env.example).

## Upgrading

```bash
git pull
docker compose up -d --build
```

The schema catches itself up on every start — new columns and indexes are added
to the database you already have. It only ever adds, never drops or retypes, so
your history is not at risk. Back up first if you like; it is one file:

```bash
cp ./data/tradezulu.db ./data/tradezulu.db.bak
```

## Development

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
TZ_SECRET_KEY=dev TZ_ADMIN_USER=dev TZ_ADMIN_PASSWORD=devpassword TZ_DEMO=1 \
  uvicorn app.main:app --reload --port 8420

cd frontend && npm install && npm run dev   # proxies /api to the above
```

```bash
cd backend  && pytest && ruff check .
cd frontend && npm run build
```

FastAPI + SQLite behind a React single-page app; the copier's sizing and risk
engine is in `backend/app/services/copier/`, kept as pure functions so every
rule is covered by tests rather than discovered on a live account.

Every metric is written out in [docs/metrics.md](docs/metrics.md). Pull requests
welcome — commits follow [Conventional Commits](https://www.conventionalcommits.org/).

## Licence

MIT — see [LICENSE](LICENSE). Not affiliated with MetaQuotes or TradingView.
