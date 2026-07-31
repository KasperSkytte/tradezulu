"""Every copy setting, exercised through the API a terminal actually calls.

The rules themselves are covered in ``test_copier_sizing`` and
``test_copier_risk``, as pure functions with their dataclasses handed to them
directly. That leaves a gap this file fills: whether a value the user typed
into the web form still means anything by the time an order is placed.

The path here is the real one, end to end -- ``PUT /api/accounts/{id}`` to save
the setting exactly as the form does, ``POST /api/agent/poll`` as the master's
terminal to publish a position, then ``POST /api/agent/poll`` as the slave's to
see what it is told to do. Nothing is mocked and no dataclass is built by hand,
so a setting that is saved under one name and read under another, or dropped in
the round trip, fails here and only here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Account, CopyEvent, CopyLink, Trade

MASTER = ("5000", "Master-Server")
SLAVE = ("9001", "Slave-Server")


def symbol_spec(symbol="EURUSD", value_per_unit=100_000.0, volume_min=0.01,
                volume_step=0.01, volume_max=100.0):
    return {
        "symbol": symbol,
        "volume_min": volume_min,
        "volume_max": volume_max,
        "volume_step": volume_step,
        "value_per_unit": value_per_unit,
        "digits": 5,
    }


def poll_body(login, server, balance, equity, positions=(), symbols=None, results=()):
    return {
        "login": login,
        "server": server,
        "name": "Terminal",
        "currency": "USD",
        "balance": balance,
        "equity": equity,
        "positions": list(positions),
        "symbols": list(symbols if symbols is not None else [symbol_spec()]),
        "results": list(results),
    }


def position(position_id=1, ticket=1, symbol="EURUSD", direction="long",
             volume=1.0, price=1.1000, sl=1.0900, tp=0.0, profit=0.0):
    return {
        "position_id": position_id,
        "ticket": ticket,
        "symbol": symbol,
        "direction": direction,
        "volume": volume,
        "open_price": price,
        "stop_loss": sl,
        "take_profit": tp,
        "profit": profit,
    }


@pytest.fixture()
def master(db):
    account = db.scalar(select(Account).where(Account.role == "master"))
    account.login, account.server = MASTER
    account.balance = account.equity = 100_000.0
    db.commit()
    return account


@pytest.fixture()
def slave(db, auth_client):
    created = auth_client.post(
        "/api/accounts",
        json={"login": SLAVE[0], "server": SLAVE[1], "name": "Slave",
              "password": "trade-password"},
    ).json()
    return db.get(Account, created["id"])


class Pair:
    """The two terminals, driven the way MetaTrader drives them."""

    def __init__(self, client, db, master, slave):
        self.client, self.db, self.master, self.slave = client, db, master, slave
        self.balance = self.equity = 10_000.0
        self.symbols = [symbol_spec()]
        self.held: list[dict] = []

    # -- configuration -----------------------------------------------------

    def configure(self, **settings):
        """Save settings through the form's own endpoint."""
        current = self.client.get("/api/accounts").json()
        row = next(a for a in current if a["id"] == self.slave.id)
        merged = {**row["settings"], **settings}
        response = self.client.put(
            f"/api/accounts/{self.slave.id}",
            json={
                "name": row["name"], "server": row["server"], "login": row["login"],
                "symbol_prefix": settings.pop("symbol_prefix", row["symbol_prefix"]),
                "symbol_suffix": settings.pop("symbol_suffix", row["symbol_suffix"]),
                "symbol_map": settings.pop("symbol_map", row["symbol_map"]),
                "settings": merged,
            },
        )
        assert response.status_code == 200, response.text
        self.db.expire_all()
        return response.json()

    def arm(self, dry_run=False):
        response = self.client.post(
            f"/api/accounts/{self.slave.id}/arm", json={"enabled": True, "dry_run": dry_run}
        )
        assert response.status_code == 200, response.text
        self.db.expire_all()

    # -- the terminals -----------------------------------------------------

    def master_holds(self, *positions):
        response = self.client.post(
            "/api/agent/poll",
            json=poll_body(*MASTER, 100_000.0, 100_000.0, positions=positions),
        )
        assert response.status_code == 200, response.text
        self.db.expire_all()

    def slave_polls(self, results=(), positions=None):
        """One slave heartbeat. Returns the commands it was given."""
        response = self.client.post(
            "/api/agent/poll",
            json=poll_body(
                *SLAVE, self.balance, self.equity,
                positions=self.held if positions is None else positions,
                symbols=self.symbols, results=results,
            ),
        )
        assert response.status_code == 200, response.text
        self.db.expire_all()
        return response.json()["commands"]

    def fill(self, commands, ticket=500):
        """Report every open command as filled, as a terminal would next poll."""
        results = []
        for index, command in enumerate(commands):
            if command["action"] != "open":
                continue
            got = ticket + index
            results.append({
                "id": command["id"], "ok": True, "action": "open",
                "master_position_id": command["master_position_id"],
                "ticket": got, "symbol": command["symbol"],
                "direction": command["direction"], "volume": command["volume"],
                "price": 1.1000, "message": "filled",
            })
            self.held.append(position(
                position_id=got, ticket=got, symbol=command["symbol"],
                direction=command["direction"], volume=command["volume"],
                sl=command["stop_loss"], tp=command["take_profit"],
            ))
        return self.slave_polls(results=results)

    # -- what happened -----------------------------------------------------

    def skips(self):
        return self.db.scalars(
            select(CopyEvent).where(
                CopyEvent.slave_account_id == self.slave.id,
                CopyEvent.outcome == "skipped",
            ).order_by(CopyEvent.id)
        ).all()

    def last_skip(self):
        rows = self.skips()
        assert rows, "expected the trade to be skipped, but nothing was"
        return rows[-1]

    def banked(self, net_pnl, days_ago=0):
        """A closed trade in the slave's journal, which is where the rules that
        care about realised profit read from."""
        day = datetime.now(timezone.utc).date() - timedelta(days=days_ago)
        when = datetime.combine(day, datetime.min.time())
        self._banked = getattr(self, "_banked", 0) + 1
        self.db.add(Trade(
            account_id=self.slave.id, position_id=90_000 + self._banked,
            symbol="EURUSD", direction="long",
            opened_at=when, closed_at=when, trade_date=day,
            volume=0.1, closed_volume=0.1, entry_price=1.1, exit_price=1.11,
            net_pnl=net_pnl, gross_profit=net_pnl,
        ))
        self.db.commit()

    def halt_reason(self):
        self.db.refresh(self.slave)
        return self.slave.copy_halt_reason


@pytest.fixture()
def pair(auth_client, db, master, slave):
    pair = Pair(auth_client, db, master, slave)
    # A new slave starts with a 2% cap on single-trade risk, which is the right
    # default and would quietly decide most of the tests below -- a 0.25 lot
    # trade on a 100 pip stop risks 2.5% of this account and never reaches the
    # sizing being tested. Each test turns on the one limit it is about.
    pair.configure(max_risk_percent_per_trade=0.0)
    return pair


def only_open(commands):
    opens = [c for c in commands if c["action"] == "open"]
    assert len(opens) == 1, f"expected exactly one open, got {commands}"
    return opens[0]


# --------------------------------------------------------------------------
# Sizing
# --------------------------------------------------------------------------


class TestSizingMode:
    """Each mode reaches the planner and decides the volume it claims to."""

    def test_fixed_lot_ignores_the_master_size(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.25)
        pair.arm()
        pair.master_holds(position(volume=4.0))
        assert only_open(pair.slave_polls())["volume"] == 0.25

    def test_multiplier_scales_the_master_size(self, pair):
        pair.configure(mode="multiplier", multiplier=0.5)
        pair.arm()
        pair.master_holds(position(volume=3.0))
        assert only_open(pair.slave_polls())["volume"] == 1.5

    def test_balance_ratio_scales_by_the_balances(self, pair):
        # Slave 10,000 against master 100,000: a tenth.
        pair.configure(mode="balance_ratio")
        pair.arm()
        pair.master_holds(position(volume=2.0))
        assert only_open(pair.slave_polls())["volume"] == 0.2

    def test_equity_ratio_uses_equity_not_balance(self, pair):
        pair.configure(mode="equity_ratio")
        pair.arm()
        pair.equity = 5_000.0  # half the balance, so half the balance-ratio size
        pair.master_holds(position(volume=2.0))
        assert only_open(pair.slave_polls())["volume"] == 0.1

    def test_risk_percent_sizes_from_the_stop(self, pair):
        # 1% of 10,000 is 100; a 100 pip stop at 100,000 per unit is 10 per lot.
        pair.configure(mode="risk_percent", risk_percent=1.0)
        pair.arm()
        pair.master_holds(position(volume=9.0, price=1.1000, sl=1.0900))
        assert only_open(pair.slave_polls())["volume"] == 0.1

    def test_risk_percent_falls_back_without_a_stop(self, pair):
        pair.configure(mode="risk_percent", risk_percent=1.0)
        pair.arm()
        pair.master_holds(position(volume=2.0, sl=0.0))
        assert only_open(pair.slave_polls())["volume"] == 0.2


class TestSizingLimits:
    def test_max_lot_clamps_the_result(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=5.0, max_lot=0.75)
        pair.arm()
        pair.master_holds(position())
        assert only_open(pair.slave_polls())["volume"] == 0.75

    def test_scale_is_applied_last(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=1.0, scale=0.25)
        pair.arm()
        pair.master_holds(position())
        assert only_open(pair.slave_polls())["volume"] == 0.25

    def test_a_size_below_the_brokers_minimum_is_refused_not_rounded_up(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.004)
        pair.arm()
        pair.master_holds(position())
        assert pair.slave_polls() == []
        assert pair.last_skip().rule == "below_minimum"

    def test_min_lot_lifts_a_result_that_is_close(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.0999, min_lot=0.1)
        pair.arm()
        pair.master_holds(position())
        assert only_open(pair.slave_polls())["volume"] == 0.1


# --------------------------------------------------------------------------
# Per-trade risk
# --------------------------------------------------------------------------


class TestPerTradeRisk:
    def test_max_risk_percent_per_trade_refuses_an_oversized_stop(self, pair):
        # 1 lot with a 100 pip stop risks 1,000 -- 10% of a 10,000 account.
        pair.configure(mode="fixed_lot", fixed_lot=1.0, max_risk_percent_per_trade=2.0)
        pair.arm()
        pair.master_holds(position(sl=1.0900))
        assert pair.slave_polls() == []
        assert "risk" in pair.last_skip().rule

    def test_within_the_risk_cap_is_allowed(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, max_risk_percent_per_trade=2.0)
        pair.arm()
        pair.master_holds(position(sl=1.0900))
        assert only_open(pair.slave_polls())["volume"] == 0.1

    def test_max_lot_per_trade_refuses_rather_than_shrinking(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=2.0, max_lot_per_trade=1.0)
        pair.arm()
        pair.master_holds(position())
        assert pair.slave_polls() == []
        assert "lot" in pair.last_skip().rule

    def test_require_stop_loss_refuses_a_naked_trade(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, require_stop_loss=True)
        pair.arm()
        pair.master_holds(position(sl=0.0))
        assert pair.slave_polls() == []
        assert "stop" in pair.last_skip().rule

    def test_require_stop_loss_permits_one_that_has_a_stop(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, require_stop_loss=True)
        pair.arm()
        pair.master_holds(position(sl=1.0900))
        assert only_open(pair.slave_polls())


# --------------------------------------------------------------------------
# Exposure limits, which need a position already open to bite
# --------------------------------------------------------------------------


class TestExposureLimits:
    def _open_one(self, pair, **settings):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, **settings)
        pair.arm()
        pair.master_holds(position(position_id=1, ticket=1))
        pair.fill(pair.slave_polls())

    def test_max_open_positions_blocks_the_second(self, pair):
        self._open_one(pair, max_open_positions=1)
        pair.master_holds(position(position_id=1, ticket=1),
                          position(position_id=2, ticket=2, symbol="EURUSD"))
        assert pair.slave_polls() == []
        assert "open" in pair.last_skip().rule

    def test_max_same_direction_blocks_another_long(self, pair):
        self._open_one(pair, max_same_direction=1)
        pair.master_holds(position(position_id=1, ticket=1),
                          position(position_id=2, ticket=2, direction="long"))
        assert pair.slave_polls() == []
        assert "direction" in pair.last_skip().rule

    def test_max_same_direction_still_allows_the_other_way(self, pair):
        self._open_one(pair, max_same_direction=1)
        pair.master_holds(position(position_id=1, ticket=1),
                          position(position_id=2, ticket=2, direction="short"))
        assert only_open(pair.slave_polls())["direction"] == "short"

    def test_max_positions_per_symbol_blocks_a_second_in_the_same_market(self, pair):
        self._open_one(pair, max_positions_per_symbol=1)
        pair.master_holds(position(position_id=1, ticket=1),
                          position(position_id=2, ticket=2, symbol="EURUSD"))
        assert pair.slave_polls() == []
        assert "symbol" in pair.last_skip().rule

    def test_max_total_lots_counts_the_incoming_trade(self, pair):
        self._open_one(pair, max_total_lots=0.15)
        pair.master_holds(position(position_id=1, ticket=1),
                          position(position_id=2, ticket=2))
        assert pair.slave_polls() == []
        assert "lots" in pair.last_skip().rule


# --------------------------------------------------------------------------
# Symbol filters
# --------------------------------------------------------------------------


class TestSymbolFilters:
    def test_a_blocked_symbol_is_not_copied(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, blocked_symbols=["EURUSD"])
        pair.arm()
        pair.master_holds(position())
        assert pair.slave_polls() == []
        assert "blocked" in pair.last_skip().rule

    def test_an_allowed_list_excludes_everything_else(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, allowed_symbols=["GBPUSD"])
        pair.arm()
        pair.master_holds(position(symbol="EURUSD"))
        assert pair.slave_polls() == []

    def test_an_allowed_list_permits_its_own_members(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, allowed_symbols=["EURUSD"])
        pair.arm()
        pair.master_holds(position())
        assert only_open(pair.slave_polls())

    def test_a_suffix_is_applied_to_the_slaves_symbol(self, pair):
        pair.symbols = [symbol_spec(symbol="EURUSD.r")]
        pair.configure(mode="fixed_lot", fixed_lot=0.1, symbol_suffix=".r")
        pair.arm()
        pair.master_holds(position(symbol="EURUSD"))
        assert only_open(pair.slave_polls())["symbol"] == "EURUSD.r"

    def test_an_explicit_map_wins(self, pair):
        pair.symbols = [symbol_spec(symbol="GOLD")]
        pair.configure(mode="fixed_lot", fixed_lot=0.1, symbol_map={"XAUUSD": "GOLD"})
        pair.arm()
        pair.master_holds(position(symbol="XAUUSD"))
        assert only_open(pair.slave_polls())["symbol"] == "GOLD"


# --------------------------------------------------------------------------
# Account-level limits: these halt rather than skip
# --------------------------------------------------------------------------


class TestAccountLimits:
    def test_equity_stop_percent_halts_and_flattens(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, equity_stop_percent=5.0)
        pair.arm()
        pair.master_holds(position(position_id=1, ticket=1))
        pair.fill(pair.slave_polls())

        pair.equity = 9_000.0  # 10% below the day's open
        commands = pair.slave_polls()

        assert pair.halt_reason(), "the account should have halted"
        assert [c["action"] for c in commands] == ["close"]

    def test_equity_stop_amount_is_a_floor_not_a_loss(self, pair):
        """The setting is the equity to stop *at*, not the loss to stop after."""
        pair.configure(mode="fixed_lot", fixed_lot=0.1, equity_stop_amount=9_500.0)
        pair.arm()
        pair.master_holds(position())
        pair.slave_polls()

        pair.equity = 9_600.0
        pair.slave_polls()
        assert not pair.halt_reason(), "still above the floor"

        pair.equity = 9_400.0
        pair.slave_polls()
        assert pair.halt_reason()

    def test_max_daily_drawdown_percent_halts(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, max_daily_drawdown_percent=3.0)
        pair.arm()
        pair.master_holds(position())
        pair.slave_polls()

        pair.equity = 9_600.0
        pair.slave_polls()
        assert pair.halt_reason()

    def test_stop_opening_halts_without_closing_anything(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, max_daily_drawdown_percent=3.0,
                       breach_action="stop_opening")
        pair.arm()
        pair.master_holds(position(position_id=1, ticket=1))
        pair.fill(pair.slave_polls())

        pair.equity = 9_600.0
        commands = pair.slave_polls()

        assert pair.halt_reason()
        assert [c for c in commands if c["action"] == "close"] == []

    def test_flatten_on_equity_stop_ignores_the_softer_limit(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, max_daily_drawdown_percent=3.0,
                       equity_stop_percent=20.0, breach_action="flatten_on_equity_stop")
        pair.arm()
        pair.master_holds(position(position_id=1, ticket=1))
        pair.fill(pair.slave_polls())

        pair.equity = 9_600.0  # past the daily limit, nowhere near the equity stop
        commands = pair.slave_polls()

        assert pair.halt_reason()
        assert [c for c in commands if c["action"] == "close"] == []

    def test_a_halted_account_opens_nothing_further(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, max_daily_drawdown_percent=3.0)
        pair.arm()
        pair.master_holds(position())
        pair.slave_polls()
        pair.equity = 9_600.0
        pair.slave_polls()

        pair.master_holds(position(position_id=2, ticket=2))
        assert [c for c in pair.slave_polls() if c["action"] == "open"] == []

    def test_resuming_clears_the_halt(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, max_daily_drawdown_percent=3.0)
        pair.arm()
        pair.master_holds(position())
        pair.slave_polls()
        pair.equity = 9_600.0
        pair.slave_polls()
        assert pair.halt_reason()

        pair.client.post(f"/api/accounts/{pair.slave.id}/resume")
        pair.db.expire_all()
        assert not pair.halt_reason()


# --------------------------------------------------------------------------
# Taking profit off the table
# --------------------------------------------------------------------------


class TestProfitRules:
    def _running_winner(self, pair, profit, **settings):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, **settings)
        pair.arm()
        pair.master_holds(position(position_id=1, ticket=1, sl=1.0900))
        pair.fill(pair.slave_polls())
        pair.held[0]["profit"] = profit
        return pair.slave_polls()

    def test_take_profit_at_amount_closes_a_big_winner(self, pair):
        commands = self._running_winner(pair, 250.0, take_profit_at_amount=200.0)
        assert [c["action"] for c in commands] == ["close"]

    def test_a_smaller_winner_is_left_alone(self, pair):
        commands = self._running_winner(pair, 150.0, take_profit_at_amount=200.0)
        assert [c for c in commands if c["action"] == "close"] == []

    def test_take_profit_at_r_closes_at_the_multiple(self, pair):
        # 0.1 lots with a 100 pip stop risks 100, so 3R is 300.
        commands = self._running_winner(pair, 320.0, take_profit_at_r=3.0)
        assert [c["action"] for c in commands] == ["close"]

    def test_below_the_r_multiple_keeps_running(self, pair):
        commands = self._running_winner(pair, 180.0, take_profit_at_r=3.0)
        assert [c for c in commands if c["action"] == "close"] == []

    def test_a_daily_profit_target_stops_opening(self, pair):
        """Measured on profit actually banked, not on equity.

        A position running at +300 has been banked by nobody -- it can still be
        given back -- so the target reads the account's closed trades.
        """
        pair.configure(mode="fixed_lot", fixed_lot=0.1, daily_profit_target_percent=2.0)
        pair.arm()
        pair.master_holds(position())
        assert only_open(pair.slave_polls())

        pair.banked(300.0)  # 3% of a 10,000 account, taken today
        assert [c for c in pair.slave_polls() if c["action"] == "open"] == []
        assert pair.halt_reason()

    def test_below_the_daily_target_keeps_trading(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, daily_profit_target_percent=2.0)
        pair.arm()
        pair.banked(150.0)
        pair.master_holds(position())
        assert only_open(pair.slave_polls())

    def test_one_day_dominating_the_profit_trips_the_consistency_cap(self, pair):
        """A prop-firm rule: no single day may be most of the total profit."""
        pair.configure(mode="fixed_lot", fixed_lot=0.1,
                       max_day_share_of_profit_percent=50.0)
        pair.arm()
        pair.banked(100.0, days_ago=3)
        pair.banked(100.0, days_ago=2)
        pair.banked(400.0)  # today is two thirds of the total

        pair.master_holds(position())
        assert [c for c in pair.slave_polls() if c["action"] == "open"] == []
        assert pair.halt_reason()

    def test_an_evenly_spread_week_is_fine(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1,
                       max_day_share_of_profit_percent=50.0)
        pair.arm()
        pair.banked(300.0, days_ago=3)
        pair.banked(300.0, days_ago=2)
        pair.banked(100.0)

        pair.master_holds(position())
        assert only_open(pair.slave_polls())


# --------------------------------------------------------------------------
# Mirroring and the lifecycle
# --------------------------------------------------------------------------


class TestMirroring:
    def test_a_moved_stop_is_pushed_to_the_slave(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, mirror_stops=True)
        pair.arm()
        pair.master_holds(position(position_id=1, ticket=1, sl=1.0900))
        pair.fill(pair.slave_polls())

        pair.master_holds(position(position_id=1, ticket=1, sl=1.0950, tp=1.1200))
        commands = pair.slave_polls()

        modify = [c for c in commands if c["action"] == "modify"]
        assert len(modify) == 1
        assert modify[0]["stop_loss"] == pytest.approx(1.0950)
        assert modify[0]["take_profit"] == pytest.approx(1.1200)

    def test_mirroring_can_be_switched_off(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1, mirror_stops=False)
        pair.arm()
        pair.master_holds(position(position_id=1, ticket=1, sl=1.0900))
        pair.fill(pair.slave_polls())

        pair.master_holds(position(position_id=1, ticket=1, sl=1.0950))
        assert [c for c in pair.slave_polls() if c["action"] == "modify"] == []

    def test_the_masters_close_closes_the_copy(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1)
        pair.arm()
        pair.master_holds(position(position_id=1, ticket=1))
        pair.fill(pair.slave_polls())

        pair.master_holds()
        commands = pair.slave_polls()
        assert [c["action"] for c in commands] == ["close"]
        assert commands[0]["ticket"] == 500

    def test_one_master_trade_produces_exactly_one_order(self, pair):
        """The duplicate-order bug, from the terminal's side of the wire.

        A closed link for the same master position used to swallow the fill,
        so the planner re-opened on every poll. Ten polls, one order.
        """
        pair.configure(mode="fixed_lot", fixed_lot=0.1)
        pair.arm(dry_run=True)
        pair.master_holds(position(position_id=1, ticket=1))
        pair.slave_polls()          # dry run records a link it never opened
        pair.arm(dry_run=False)     # going live must clear it

        opened = pair.fill(pair.slave_polls())
        for _ in range(10):
            opened += pair.slave_polls()

        assert [c for c in opened if c["action"] == "open"] == []
        links = pair.db.scalars(
            select(CopyLink).where(
                CopyLink.slave_account_id == pair.slave.id, CopyLink.status == "open"
            )
        ).all()
        assert len(links) == 1


class TestDryRun:
    def test_nothing_is_sent_to_the_terminal(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1)
        pair.arm(dry_run=True)
        pair.master_holds(position())
        assert pair.slave_polls() == []

    def test_but_it_still_records_what_it_would_have_done(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1)
        pair.arm(dry_run=True)
        pair.master_holds(position())
        pair.slave_polls()

        events = pair.db.scalars(
            select(CopyEvent).where(
                CopyEvent.slave_account_id == pair.slave.id,
                CopyEvent.outcome == "dry_run",
            )
        ).all()
        assert len(events) == 1
        assert events[0].volume == 0.1

    def test_disarming_stops_everything(self, pair):
        pair.configure(mode="fixed_lot", fixed_lot=0.1)
        pair.arm()
        pair.client.post(
            f"/api/accounts/{pair.slave.id}/arm", json={"enabled": False, "dry_run": True}
        )
        pair.master_holds(position())
        assert pair.slave_polls() == []
