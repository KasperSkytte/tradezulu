"""Generate a plausible trading history so the UI can be explored offline.

Enabled with ``TZ_DEMO=1``. It only ever runs when the database has no trades,
so it can never overwrite real data.
"""

from __future__ import annotations

import logging
import random
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select

from .db import SessionLocal
from .models import Account, Candle, DayNote, EquityPoint, Tag, Trade
from .services.aggregation import compute_derived, resolve_account_size
from .services.appsettings import get_app_settings

log = logging.getLogger(__name__)

SYMBOLS = [
    # symbol, typical price, tick value per 1.0 price move per lot, digits
    ("EURUSD", 1.0850, 100_000.0, 5),
    ("GBPUSD", 1.2700, 100_000.0, 5),
    ("USDJPY", 157.20, 670.0, 3),
    ("XAUUSD", 2350.0, 100.0, 2),
    ("US30", 39000.0, 1.0, 1),
    ("NAS100", 18500.0, 1.0, 1),
]

SETUPS = ["London breakout", "NY reversal", "Trend pullback", "Range fade", "News fade"]


def seed_demo_data(days: int = 120, seed: int = 7) -> int:
    rng = random.Random(seed)
    with SessionLocal() as db:
        if db.scalar(select(func.count()).select_from(Trade)):
            log.info("Demo data skipped: trades already exist")
            return 0

        account = db.scalar(select(Account).order_by(Account.id).limit(1))
        if account is None:
            account = Account(login="5000123", name="Demo account", is_default=True)
            db.add(account)
            db.flush()
        # The placeholder account created on first boot is adopted, and it is
        # called "Default account" with a login of 0 -- which reads as a bug in
        # every screenshot taken of it.
        if account.login in ("", "0"):
            account.login = "5000123"
            account.name = "Demo account"
            account.server = account.server or "DemoBroker-Live"
        account.name = account.name or "Demo account"
        account.broker = account.broker or "Demo Broker"
        account.currency = "USD"
        account.balance = 25_000.0
        account.initial_balance = 25_000.0
        account.last_sync_at = datetime.now(timezone.utc).replace(tzinfo=None)
        account.last_sync_source = "demo"

        tags = list(db.scalars(select(Tag)).all())
        mistake_tags = [t for t in tags if t.category == "mistake"]
        emotion_tags = [t for t in tags if t.category == "emotion"]
        setup_tags = [t for t in tags if t.category == "setup"]

        config = get_app_settings(db)
        account_size = resolve_account_size(account, config["risk"])

        now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
        created = 0
        position_id = 900_000

        for day_offset in range(days, -1, -1):
            day = now - timedelta(days=day_offset)
            if day.weekday() >= 5:
                continue
            if rng.random() < 0.25:  # not every day is a trading day
                continue

            for _ in range(rng.choice([1, 1, 2, 2, 3, 4])):
                symbol, base_price, value_per_unit, digits = rng.choice(SYMBOLS)
                direction = rng.choice(["long", "short"])
                sign = 1 if direction == "long" else -1

                entry = round(base_price * (1 + rng.gauss(0, 0.004)), digits)
                risk_pct = rng.choice([0.5, 0.75, 1.0, 1.0, 1.25])
                risk_money = account_size * risk_pct / 100

                volume = round(max(0.01, risk_money / (value_per_unit * base_price * 0.002)), 2)
                stop_distance = risk_money / (value_per_unit * volume)
                stop = round(entry - sign * stop_distance, digits)
                target_r = rng.choice([1.5, 2.0, 2.0, 2.5, 3.0])
                target = round(entry + sign * stop_distance * target_r, digits)

                roll = rng.random()
                if roll < 0.09:
                    realized_r = rng.uniform(-0.08, 0.08)  # breakeven / scratch
                elif roll < 0.47:
                    realized_r = rng.uniform(0.6, target_r * rng.uniform(0.8, 1.1))
                elif roll < 0.55:
                    realized_r = rng.uniform(target_r, target_r + 1.5)  # runner
                else:
                    realized_r = -rng.uniform(0.7, 1.15)

                exit_price = round(entry + sign * stop_distance * realized_r, digits)
                gross = realized_r * risk_money
                commission = -round(volume * 3.5, 2)
                swap = round(rng.uniform(-1.2, 0.4), 2) if rng.random() < 0.3 else 0.0

                opened_at = day.replace(
                    hour=rng.randint(7, 20), minute=rng.choice([0, 5, 15, 30, 45]), second=0
                )
                duration = timedelta(minutes=rng.choice([7, 18, 35, 55, 90, 150, 240, 420]))

                position_id += 1
                trade = Trade(
                    account_id=account.id,
                    position_id=position_id,
                    symbol=symbol,
                    direction=direction,
                    opened_at=opened_at,
                    closed_at=opened_at + duration,
                    volume=volume,
                    closed_volume=volume,
                    entry_price=entry,
                    exit_price=exit_price,
                    gross_profit=round(gross, 2),
                    commission=commission,
                    swap=swap,
                    value_per_unit=value_per_unit,
                    digits=digits,
                    initial_stop=stop,
                    initial_target=target,
                    stop_source="mt5",
                    target_source="mt5",
                    setup=rng.choice(SETUPS),
                    rating=rng.choice([None, 2, 3, 3, 4, 4, 5]),
                    source="demo",
                    comment="demo",
                )

                chosen: list[Tag] = []
                if setup_tags and rng.random() < 0.7:
                    chosen.append(rng.choice(setup_tags))
                if realized_r < -0.3 and mistake_tags and rng.random() < 0.6:
                    chosen.append(rng.choice(mistake_tags))
                if emotion_tags and rng.random() < 0.25:
                    chosen.append(rng.choice(emotion_tags))
                trade.tags = list({t.id: t for t in chosen}.values())

                if rng.random() < 0.35:
                    trade.notes = rng.choice(
                        [
                            "Clean setup, followed the plan exactly.",
                            "Entered before the level was confirmed. Impatient.",
                            "Should have trailed the stop instead of taking the fixed target.",
                            "News spike hit my stop by a tick. Nothing to do differently.",
                            "Size was too big for the volatility of the session.",
                            "Textbook execution. Repeat this one.",
                        ]
                    )

                db.add(trade)
                compute_derived(
                    trade, config["risk"], account_size, config["general"]["timezone"]
                )
                created += 1

        db.flush()

        # Everything an account collects for itself, so the demo exercises the
        # same paths a real one does rather than only the trade table: a
        # balance that agrees with the trades, a sample of it per day, candles
        # to draw a chart from, and a couple of days somebody wrote about.
        trades = list(db.scalars(select(Trade).where(Trade.account_id == account.id)))
        _settle_balance(db, account, trades)
        _seed_equity(db, account, trades)
        _seed_candles(db, rng, trades)
        _seed_notes(db, rng, trades)

        db.commit()
        log.info("Seeded %d demo trades", created)
        return created


def _settle_balance(db, account: Account, trades: list[Trade]) -> None:
    """Make the account worth what its trades say it is worth.

    Every percentage in the journal is reconstructed backwards from the
    recorded balance, so a demo whose balance was a round number unrelated to
    its own history would report returns that are wrong in exactly the way
    this is meant to demonstrate is impossible.
    """
    account.balance = round(
        account.initial_balance + sum(t.net_pnl or 0.0 for t in trades), 2
    )
    account.equity = account.balance


def _seed_equity(db, account: Account, trades: list[Trade]) -> None:
    """One balance sample per trading day, as a terminal would report."""
    running = account.initial_balance
    by_day: dict[date, float] = {}
    for trade in sorted(trades, key=lambda t: t.closed_at or t.opened_at):
        running += trade.net_pnl or 0.0
        by_day[(trade.closed_at or trade.opened_at).date()] = running

    for day, balance in by_day.items():
        db.add(
            EquityPoint(
                account_id=account.id,
                time=datetime.combine(day, time(23, 59)),
                balance=round(balance, 2),
                equity=round(balance, 2),
                open_positions=0,
            )
        )


#: How many of the most recent trades get candles. Every one of them would be
#: a quarter of a million bars for a chart nobody opens; the newest are the
#: ones anybody clicks into.
CANDLE_TRADES = 12
CANDLE_PADDING = timedelta(hours=12)


def _seed_candles(db, rng: random.Random, trades: list[Trade]) -> None:
    """M5 bars around the newest trades, so the replay has something to draw.

    One walk per symbol rather than one per trade. Two trades hours apart share
    the hours between them, and giving each its own walk left the price jumping
    between them -- a chart with a hole in it, which is exactly what somebody
    reading these screenshots would spot first.

    The walk drifts on its own and is pulled towards the trade's own prices
    while a position is open, so the candles actually go where the trade says
    they went. It is fabricated and says so; the trade's prices are the only
    fixed points, and they are where the chart's markers land.
    """
    recent = sorted(trades, key=lambda t: t.closed_at or t.opened_at)[-CANDLE_TRADES:]
    by_symbol: dict[str, list[Trade]] = {}
    for trade in recent:
        if trade.closed_at is not None:
            by_symbol.setdefault(trade.symbol, []).append(trade)

    span = timedelta(minutes=5)
    for symbol, group in by_symbol.items():
        group.sort(key=lambda t: t.opened_at)
        start = _floor_5m(group[0].opened_at - CANDLE_PADDING)
        end = group[-1].closed_at + CANDLE_PADDING
        digits = group[0].digits

        # A bar of this instrument moves about an eighth of the stop distance,
        # which keeps the noise in proportion to what the trades risked.
        stops = [
            abs(t.entry_price - t.initial_stop)
            for t in group
            if t.initial_stop
        ]
        step = (sum(stops) / len(stops) / 8) if stops else group[0].entry_price * 0.0002

        when = start
        price = group[0].entry_price * (1 + rng.gauss(0, 0.002))
        while when <= end:
            live = next(
                (t for t in group if t.opened_at <= when <= t.closed_at), None
            )
            if live is not None:
                held = max((live.closed_at - live.opened_at).total_seconds(), 1.0)
                progress = (when - live.opened_at).total_seconds() / held
                target = live.entry_price + (
                    (live.exit_price or live.entry_price) - live.entry_price
                ) * progress
                price += (target - price) * 0.35
            else:
                # Between trades, drift back towards the next entry so the
                # price arrives where the next one begins.
                ahead = next((t for t in group if t.opened_at > when), None)
                if ahead is not None:
                    gap = max((ahead.opened_at - when).total_seconds(), 1.0)
                    pull = min(0.05, span.total_seconds() / gap)
                    price += (ahead.entry_price - price) * pull
            price += rng.gauss(0, step)

            close = price + rng.gauss(0, step / 2)
            high = max(price, close) + abs(rng.gauss(0, step / 2))
            low = min(price, close) - abs(rng.gauss(0, step / 2))
            db.add(
                Candle(
                    symbol=symbol,
                    timeframe="M5",
                    time=when,
                    open=round(price, digits),
                    high=round(high, digits),
                    low=round(low, digits),
                    close=round(close, digits),
                    volume=float(rng.randint(40, 900)),
                )
            )
            price = close
            when += span


def _floor_5m(when: datetime) -> datetime:
    """Bars sit on the clock, so overlapping windows produce the same ones."""
    return when.replace(minute=when.minute - when.minute % 5, second=0, microsecond=0)


NOTES = [
    ("Two clean setups, both taken. Left the third alone because it was late in the session.",
     "good"),
    ("Chased an entry after missing the first one. That is the whole day's loss right there.",
     "frustrated"),
    ("Stuck to size on a day that wanted more. Fine.", "calm"),
]


def _seed_notes(db, rng: random.Random, trades: list[Trade]) -> None:
    """A few days somebody wrote about, so the calendar shows its markers.

    One note per day, and the day is drawn at random -- so two draws can land
    on the same one. The database was asked whether a note existed, which is
    the right question and the wrong place to ask it: the session does not
    autoflush, so notes added a moment earlier in this same loop were invisible
    to it and the duplicate only surfaced as an IntegrityError at commit. That
    took the whole seed down, and with it `docker compose run ... demo`, on
    whichever dates the draw happened to collide.
    """
    days = sorted({(t.closed_at or t.opened_at).date() for t in trades})
    if not days:
        return
    taken = {note.day for note in db.scalars(select(DayNote))}
    for content, mood in NOTES:
        day = rng.choice(days[-40:])
        if day in taken:
            continue
        taken.add(day)
        db.add(DayNote(day=day, content=content, mood=mood))


if __name__ == "__main__":  # pragma: no cover
    from .db import init_db

    logging.basicConfig(level=logging.INFO)
    init_db()
    seed_demo_data()
