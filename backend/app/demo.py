"""Generate a plausible trading history so the UI can be explored offline.

Enabled with ``TZ_DEMO=1``. It only ever runs when the database has no trades,
so it can never overwrite real data.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from .db import SessionLocal
from .models import Account, Tag, Trade
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

        db.commit()
        log.info("Seeded %d demo trades", created)
        return created


if __name__ == "__main__":  # pragma: no cover
    from .db import init_db

    logging.basicConfig(level=logging.INFO)
    init_db()
    seed_demo_data()
