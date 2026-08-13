"""Reconstructing what an account was worth, and when.

Every percentage in the journal divides by one of these numbers, so they are
worth testing on their own rather than through whatever page happens to show
one.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.models import Account, Deal, EquityPoint, Trade
from app.services.balances import (
    attach_daily_returns,
    balance_before_trades,
    current_balance,
    opening_balance,
)


def account(db, **kwargs) -> Account:
    row = Account(login="4242", server="Test-Server", name="Balances", role="slave", **kwargs)
    db.add(row)
    db.flush()
    return row


def closed(db, account_id: int, when: datetime, net: float) -> Trade:
    trade = Trade(
        account_id=account_id,
        position_id=int(when.timestamp()),
        symbol="EURUSD",
        direction="long",
        opened_at=when,
        closed_at=when,
        trade_date=when.date(),
        volume=1.0,
        closed_volume=1.0,
        entry_price=1.1,
        exit_price=1.1,
        gross_profit=net,
        net_pnl=net,
        outcome="win" if net > 0 else "loss",
    )
    db.add(trade)
    db.flush()
    return trade


def deposit(db, account_id: int, when: datetime, amount: float) -> None:
    db.add(
        Deal(
            account_id=account_id,
            ticket=int(when.timestamp()),
            deal_type=2,  # a balance operation
            profit=amount,
            time=when,
        )
    )
    db.flush()


class TestCurrentBalance:
    def test_what_the_broker_says_wins(self, db):
        """The one number in the chain that is not inferred.

        An initial deposit typed in once plus every trade ever recorded is a
        guess that assumes the history is complete and nothing was withdrawn.
        On this project's own data that guess said 37,893 for an account
        holding 235, and every percentage taken from it was wrong by two
        orders of magnitude while looking entirely reasonable.
        """
        row = account(db, initial_balance=25_000.0, balance=235.51)
        closed(db, row.id, datetime(2026, 6, 1, 10), 500.0)
        assert current_balance(db, row) == pytest.approx(235.51)

    def test_an_imported_account_falls_back_to_its_deposit(self, db):
        """No terminal has ever logged in, so there is nothing better."""
        row = account(db, initial_balance=1_000.0, balance=0.0)
        closed(db, row.id, datetime(2026, 6, 1, 10), 250.0)
        assert current_balance(db, row) == pytest.approx(1_250.0)

    def test_nothing_known_is_nothing_claimed(self, db):
        assert current_balance(db, account(db, initial_balance=0.0, balance=0.0)) is None
        assert current_balance(db, None) is None


class TestBalanceBeforeEachTrade:
    def test_it_walks_back_from_today(self, db):
        row = account(db, balance=1_150.0)
        first = closed(db, row.id, datetime(2026, 6, 1, 10), 100.0)
        second = closed(db, row.id, datetime(2026, 6, 2, 10), 50.0)

        before = balance_before_trades(db, {row.id})

        assert before[first.id] == pytest.approx(1_000.0)
        assert before[second.id] == pytest.approx(1_100.0)

    def test_a_deposit_is_not_mistaken_for_profit(self, db):
        """Otherwise every trade after a top-up is measured against it.

        MetaTrader records deposits and withdrawals as balance deals, so an
        account a terminal has been watching reconstructs exactly.
        """
        row = account(db, balance=2_100.0)
        first = closed(db, row.id, datetime(2026, 6, 1, 10), 100.0)
        deposit(db, row.id, datetime(2026, 6, 2, 9), 1_000.0)
        second = closed(db, row.id, datetime(2026, 6, 3, 10), 100.0)

        before = balance_before_trades(db, {row.id})

        assert before[first.id] == pytest.approx(900.0)
        assert before[second.id] == pytest.approx(2_000.0)

    def test_reaching_back_past_the_funding_gives_no_answer(self, db):
        """The account existed before the history anyone has here.

        Walking back through more profit than the account is worth crosses
        zero, and a percentage of a negative balance is not a small number --
        it is the wrong sign.
        """
        row = account(db, balance=100.0)
        old = closed(db, row.id, datetime(2026, 6, 1, 10), 5_000.0)
        recent = closed(db, row.id, datetime(2026, 6, 2, 10), 20.0)

        before = balance_before_trades(db, {row.id})

        assert old.id not in before
        assert before[recent.id] == pytest.approx(80.0)


class TestTradesNewerThanEverySample:
    """A trade that closed after the last recorded balance still has one.

    Two ways this happens on a live account, and both are ordinary: the
    terminal reports its balance every minute or so, and a trade closed
    between two of those reports is newer than every sample; and MetaTrader
    deal times are the *broker's* clock, which for most brokers runs two or
    three hours ahead of UTC, so the newest trades look like they are in the
    future.

    Either way, refusing to answer meant the newest rows -- the ones anybody
    is actually looking at -- showed a dash where the rest of the column had
    numbers.
    """

    def test_a_trade_after_the_last_sample_still_gets_a_balance(self, db):
        row = account(db, balance=1_000.0)
        row.last_sync_at = datetime(2026, 6, 10, 12, 0)
        db.add(
            EquityPoint(
                account_id=row.id, time=datetime(2026, 6, 10, 12, 0),
                balance=1_000.0, equity=1_000.0,
            )
        )
        # Closed three hours "later" -- the broker's clock, or simply between
        # two reports.
        recent = closed(db, row.id, datetime(2026, 6, 10, 15, 0), 50.0)

        before = balance_before_trades(db, {row.id})

        assert before[recent.id] == pytest.approx(1_000.0)

    def test_several_of_them_stack_up_in_order(self, db):
        row = account(db, balance=1_000.0)
        row.last_sync_at = datetime(2026, 6, 10, 12, 0)
        db.add(
            EquityPoint(
                account_id=row.id, time=datetime(2026, 6, 10, 12, 0),
                balance=1_000.0, equity=1_000.0,
            )
        )
        first = closed(db, row.id, datetime(2026, 6, 10, 14, 0), 50.0)
        second = closed(db, row.id, datetime(2026, 6, 10, 15, 0), 25.0)

        before = balance_before_trades(db, {row.id})

        assert before[first.id] == pytest.approx(1_000.0)
        assert before[second.id] == pytest.approx(1_050.0), "the first one moved the balance"

    def test_the_older_ones_are_unaffected(self, db):
        row = account(db, balance=1_000.0)
        row.last_sync_at = datetime(2026, 6, 10, 12, 0)
        db.add(
            EquityPoint(
                account_id=row.id, time=datetime(2026, 6, 10, 12, 0),
                balance=1_000.0, equity=1_000.0,
            )
        )
        earlier = closed(db, row.id, datetime(2026, 6, 10, 9, 0), 100.0)
        later = closed(db, row.id, datetime(2026, 6, 10, 15, 0), 50.0)

        before = balance_before_trades(db, {row.id})

        assert before[earlier.id] == pytest.approx(900.0), "walked back from the sample"
        assert before[later.id] == pytest.approx(1_000.0), "walked forward from it"


class TestOpeningBalance:
    def test_a_period_opens_where_the_one_before_it_closed(self, db):
        row = account(db, balance=1_300.0)
        closed(db, row.id, datetime(2026, 5, 20, 10), 100.0)
        closed(db, row.id, datetime(2026, 6, 10, 10), 200.0)

        assert opening_balance(db, row.id, date(2026, 6, 1)) == pytest.approx(1_100.0)

    def test_no_account_no_balance(self, db):
        assert opening_balance(db, None, date(2026, 6, 1)) is None


class TestDailyReturns:
    def test_a_day_is_measured_against_the_previous_close(self, db):
        """20 made on a 200 account is +10%, whatever it started the year at."""
        row = account(db, balance=220.0)
        closed(db, row.id, datetime(2026, 6, 10, 10), 20.0)

        days = attach_daily_returns(
            db, row.id, [{"date": date(2026, 6, 10), "net_pnl": 20.0}]
        )

        assert days[0]["start_balance"] == pytest.approx(200.0)
        assert days[0]["return_pct"] == pytest.approx(10.0)

    def test_it_compounds(self, db):
        """The second day is measured against the balance the first day left.

        Judging both against the opening figure would call two equal days
        equal, when the second was a smaller share of a bigger account.
        """
        row = account(db, balance=1_200.0)
        closed(db, row.id, datetime(2026, 6, 10, 10), 100.0)
        closed(db, row.id, datetime(2026, 6, 11, 10), 100.0)

        days = attach_daily_returns(
            db,
            row.id,
            [
                {"date": date(2026, 6, 10), "net_pnl": 100.0},
                {"date": date(2026, 6, 11), "net_pnl": 100.0},
            ],
        )

        assert days[0]["start_balance"] == pytest.approx(1_000.0)
        assert days[0]["return_pct"] == pytest.approx(10.0)
        assert days[1]["start_balance"] == pytest.approx(1_100.0)
        assert days[1]["return_pct"] == pytest.approx(9.0909, rel=1e-3)

    def test_nothing_is_measured_across_accounts(self, db):
        """No shared morning balance, so no percentage rather than a wrong one."""
        days = attach_daily_returns(db, None, [{"date": date(2026, 6, 10), "net_pnl": 50.0}])
        assert days[0]["return_pct"] is None
        assert "start_balance" not in days[0]

    def test_later_trades_are_wound_back_first(self, db):
        """A month in view is not the end of the account's history.

        Everything after the last day shown still moved the balance, so
        without unwinding it first every day in the month would be measured
        against money it never had.
        """
        row = account(db, balance=500.0)
        closed(db, row.id, datetime(2026, 6, 10, 10), 100.0)
        closed(db, row.id, datetime(2026, 7, 5, 10), 300.0)

        days = attach_daily_returns(
            db, row.id, [{"date": date(2026, 6, 10), "net_pnl": 100.0}]
        )

        assert days[0]["start_balance"] == pytest.approx(100.0)
        assert days[0]["return_pct"] == pytest.approx(100.0)


class TestCreditIsPartOfTheArithmetic:
    """A bonus the broker adds and takes away again.

    It moves the balance exactly as a deposit does, so a reconstruction that
    cannot see it walks off into numbers the account never had. On the
    installation this was found on, five credit withdrawals in one evening
    took the walk to minus 7.69 and twenty-two trades lost their percentages
    with it -- every one of them came back once credit was counted.
    """

    def credit(self, db, account_id: int, when: datetime, amount: float) -> None:
        db.add(
            Deal(
                account_id=account_id,
                ticket=int(when.timestamp()) + 500_000,
                deal_type=3,  # credit
                profit=amount,
                time=when,
            )
        )
        db.flush()

    def test_a_credit_that_is_taken_back_keeps_the_walk_on_its_feet(self, db):
        row = account(db, balance=40.0)
        # Funded small, propped up by credit, then the credit is pulled and
        # the account trades on afterwards.
        first = closed(db, row.id, datetime(2026, 6, 1, 10), -8.0)
        self.credit(db, row.id, datetime(2026, 6, 1, 12), 30.0)
        self.credit(db, row.id, datetime(2026, 6, 1, 18), -30.0)
        deposit(db, row.id, datetime(2026, 6, 2, 9), 25.0)
        second = closed(db, row.id, datetime(2026, 6, 3, 10), 3.0)

        before = balance_before_trades(db, {row.id})

        # Without credit in the walk the first trade lands below zero and is
        # dropped; with it, both trades have the balance they really had.
        assert before[first.id] == pytest.approx(20.0)
        assert before[second.id] == pytest.approx(37.0)

    def test_credit_moves_the_balance_like_a_deposit_does(self, db):
        row = account(db, balance=100.0)
        self.credit(db, row.id, datetime(2026, 6, 1, 9), 40.0)
        after = closed(db, row.id, datetime(2026, 6, 2, 10), 10.0)

        before = balance_before_trades(db, {row.id})

        assert before[after.id] == pytest.approx(90.0)
