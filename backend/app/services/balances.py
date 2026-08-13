"""What an account was worth at each point in its history.

Every percentage in the journal divides by one of these numbers, so getting
them wrong is not a display problem -- it produces figures that look precise
and describe an account nobody has.

Balances are reconstructed *backwards* from a recorded one, never forwards
from a deposit figure typed in once. A forward walk assumes the history is
complete and that nothing was ever withdrawn; on this project's own data it
claimed 37,893 for an account holding 235, and every "percent of balance"
taken from it was wrong by two orders of magnitude while looking entirely
reasonable.

Which recorded balance matters. Each terminal reports its balance every minute
and those samples are kept, so the walk starts from the *closest* one at or
after the moment being asked about, rather than from today. That keeps any
disagreement between the samples and the deal history -- an unrecorded
withdrawal, a broker adjustment, an import covering only part of the year --
inside the gap it happened in, instead of letting it move every figure before
it.

Deposits and withdrawals are part of the walk. MetaTrader records them as
balance deals, which the Expert Advisor reports like any other, so an account
it has been watching reconstructs exactly.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Account, Deal, EquityPoint, Trade

#: MetaTrader's deal type for a balance operation -- a deposit or a withdrawal.
#: It moves the balance without being a trade.
DEAL_TYPE_BALANCE = 2

#: And credit: a bonus the broker adds to the balance and can take away again.
#: It moves the balance exactly as a deposit does, so leaving it out of the
#: reconstruction breaks the arithmetic -- an account here walked to minus
#: 7.69 because five credit withdrawals in one evening were invisible to it,
#: and twenty-two trades lost their percentages as a result.
#:
#: It is still not the account's money. It cannot be withdrawn, so it is
#: counted while reconstructing what the broker's balance *was* and then taken
#: back out of what the account is *worth*.
DEAL_TYPE_CREDIT = 3


@dataclass(frozen=True)
class Event:
    """Something that moved the balance."""

    when: datetime
    day: date
    amount: float
    #: The trade it was, if it was one. Balance operations are not trades.
    trade_id: int | None
    #: Credit rather than money: it moved the broker's balance and it is not
    #: the account's to keep.
    credit: bool = False


def current_balance(db: Session, account: Account | None) -> float | None:
    """What the account is worth now, if anything can be said about it.

    The reported balance is preferred over anything derived from it. Where
    there is none -- history imported from a file, no terminal ever logged in
    -- the deposit plus every recorded trade is all that is left, so it is
    used rather than refusing to answer, carrying the assumptions it always
    did.
    """
    if account is None:
        return None
    if account.balance and account.balance > 0:
        return float(account.balance)
    if account.initial_balance and account.initial_balance > 0:
        closed = db.scalars(
            select(Trade.net_pnl).where(
                Trade.account_id == account.id, Trade.closed_at.is_not(None)
            )
        )
        return float(account.initial_balance) + sum(float(value or 0.0) for value in closed)
    return None


def _anchors(db: Session, account: Account) -> list[tuple[datetime, float]]:
    """Recorded balances to measure back from, oldest first.

    One per day from the terminal's own reports, plus whatever the account is
    worth now. A day is enough: the events between an anchor and the moment
    asked about are unwound exactly, so more samples would only shorten the
    stretch over which a disagreement can drift.
    """
    last_of_day = (
        select(func.max(EquityPoint.time))
        .where(EquityPoint.account_id == account.id)
        .group_by(func.date(EquityPoint.time))
    )
    samples = [
        (time, float(balance))
        for time, balance in db.execute(
            select(EquityPoint.time, EquityPoint.balance)
            .where(EquityPoint.account_id == account.id, EquityPoint.time.in_(last_of_day))
            .order_by(EquityPoint.time)
        )
        if balance and balance > 0
    ]

    now = current_balance(db, account)
    if now is not None:
        # Latest wins, and it is the one the user sees on the account page.
        when = account.last_sync_at or datetime.max
        if samples and samples[-1][0] >= when:
            samples[-1] = (samples[-1][0], now)
        else:
            samples.append((when, now))
    return samples


def _events(db: Session, account_id: int) -> list[Event]:
    """Everything that moved this account's balance, oldest first."""
    events = [
        Event(closed_at, trade_date, float(net_pnl or 0.0), trade_id)
        for trade_id, closed_at, trade_date, net_pnl in db.execute(
            select(Trade.id, Trade.closed_at, Trade.trade_date, Trade.net_pnl).where(
                Trade.account_id == account_id, Trade.closed_at.is_not(None)
            )
        )
    ]
    events += [
        Event(time, time.date(), float(profit or 0.0), None, deal_type == DEAL_TYPE_CREDIT)
        for time, profit, deal_type in db.execute(
            select(Deal.time, Deal.profit, Deal.deal_type).where(
                Deal.account_id == account_id,
                Deal.deal_type.in_((DEAL_TYPE_BALANCE, DEAL_TYPE_CREDIT)),
            )
        )
        if time is not None
    ]
    events.sort(key=lambda event: (event.when, event.trade_id or 0))
    return events


def _outstanding_credit(events: list[Event]) -> dict[int, float]:
    """How much credit is sitting in the balance at each event, by position.

    Walked forwards from nothing, because that is the only direction credit
    makes sense in: it starts at zero, the broker adds some, the broker takes
    it back. Keyed by index rather than by time so two events in the same
    second keep their order.
    """
    running = 0.0
    out: dict[int, float] = {}
    for index, event in enumerate(events):
        out[index] = running
        if event.credit:
            running += event.amount
    return out


def _walk(db: Session, account_id: int) -> list[tuple[Event, float | None]]:
    """Each event with the balance immediately before it, oldest first.

    Two directions, meeting at the newest anchor.

    Backwards from there for everything older, adopting the closest anchor at
    or after each event. A walk that reaches back past the account's funding
    goes negative -- the money was there before the first trade anyone here
    knows about -- and those events get no balance rather than a percentage of
    a number that cannot be one.

    Forwards for anything newer, which is not an edge case: a terminal reports
    its balance every minute or so, and MetaTrader's deal times are the
    *broker's* clock, which for most brokers runs hours ahead of UTC. Between
    them, the newest trades routinely sit after every recorded balance -- and
    those are the rows anybody is actually looking at. They used to show a
    dash while the rest of the column had numbers.
    """
    account = db.get(Account, account_id)
    if account is None:
        return []
    anchors = _anchors(db, account)
    events = _events(db, account_id)
    if not anchors:
        return [(event, None) for event in events]

    newest_at, newest_balance = anchors[-1]
    out: list[tuple[Event, float | None]] = []

    # ... older than the newest anchor: backwards, from whichever anchor is
    # closest after each event.
    older = [event for event in events if event.when <= newest_at]
    running: float | None = None
    for event in reversed(older):
        while anchors and anchors[-1][0] >= event.when:
            running = anchors.pop()[1]
        if running is None:
            out.append((event, None))
            continue
        before = running - event.amount
        # A reconstruction that still crosses zero with every balance event
        # counted means the history is short of one -- money left without a
        # record of it -- and that is unknown rather than zero. Credit taking
        # the account underwater is a different thing and is handled where the
        # money figure is worked out, not here.
        out.append((event, before if before > 0 else None))
        running = before
    out.reverse()

    # ... and newer: forwards from that same anchor, adding each event as it
    # goes, so a run of them stacks up in the order they happened.
    running = newest_balance
    for event in [event for event in events if event.when > newest_at]:
        out.append((event, running if running > 0 else None))
        running += event.amount

    return out


def balance_before_trades(db: Session, account_ids: set[int]) -> dict[int, float]:
    """The balance immediately before each closed trade of these accounts.

    One walk per account rather than a query per trade: a page of fifty would
    otherwise be fifty aggregates, and the whole history has to be walked for
    any of it to mean anything.
    """
    out: dict[int, float] = {}
    for account_id in account_ids:
        for event, before in _walk(db, account_id):
            if event.trade_id is not None and before is not None:
                out[event.trade_id] = round(before, 2)
    return out


def opening_balance(db: Session, account_id: int | None, day: date) -> float | None:
    """What the account was worth on the morning of ``day``.

    A period is a window on an account that has been growing or shrinking all
    along, so judging one month against January's balance describes a
    different month.
    """
    if account_id is None:
        return None
    walk = _walk(db, account_id)
    # The earliest balance in the period that can be reconstructed at all.
    # Where the samples and the deal history disagree -- an unrecorded
    # withdrawal, an import covering only part of the year -- the walk crosses
    # zero and the days before that point have no balance. Skipping that
    # stretch answers with the first day that does; refusing to answer would
    # take the whole period's return and drawdown with it.
    for event, before in walk:
        if event.day >= day and before is not None:
            return round(before, 2)
    # Nothing happened on or after that day, so it opened at whatever it
    # closed the last event at -- or at today's balance if there were none.
    if walk:
        event, before = walk[-1]
        return round(before + event.amount, 2) if before is not None else None
    return current_balance(db, db.get(Account, account_id))


def attach_daily_returns(
    db: Session, account_id: int | None, days: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Give each day its opening balance and its result as a share of it.

    The opening balance is the previous day's closing balance, which is what
    anyone comparing two days has in mind. Compounding follows on its own: a
    good day makes the next one a smaller percentage, because there is more
    money for it to be a percentage of.

    Nothing is attached without a single account in scope. Several accounts
    have no shared morning balance, and dividing by whichever one was handy
    would be a number rather than an answer.
    """
    if not days:
        return days

    openings: dict[date, float] = {}
    if account_id is not None:
        for event, before in _walk(db, account_id):
            if before is not None:
                openings.setdefault(event.day, round(before, 2))

    for day in days:
        opening = openings.get(_as_date(day["date"]))
        net = float(day.get("net_pnl") or 0.0)
        if opening:
            day["start_balance"] = opening
            day["return_pct"] = round(net / opening * 100.0, 4)
        else:
            day["return_pct"] = None
            day.pop("start_balance", None)
    return days


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _money_timeline(db: Session, account_id: int) -> list[tuple[datetime, float]]:
    """What the account was worth, in order, at each thing that moved it.

    Worth, not balance: credit is counted while reconstructing the broker's
    figure and then taken back out, because it cannot be withdrawn. Floored at
    zero -- an account can be underwater on credit, and a negative denominator
    turns a loss into a positive percentage.
    """
    events = _events(db, account_id)
    credit = _outstanding_credit(events)
    out: list[tuple[datetime, float]] = []
    for index, (event, before) in enumerate(_walk(db, account_id)):
        if before is None:
            continue
        out.append((event.when, max(before - credit.get(index, 0.0), 0.0)))
    return out


def equity_at_open(db: Session, trades: Sequence[Trade]) -> dict[int, float]:
    """What each trade had behind it at the moment it was opened.

    Equity rather than balance, and at the open rather than at the close,
    because that is what the trade actually risked. A balance says nothing
    about an account sitting ten per cent underwater on positions that have
    not closed yet, and a figure taken at the close is measured against money
    the trade itself had already moved.

    Recorded equity when there is a sample near enough to mean it. Otherwise
    the reconstruction, which for a trade opened with nothing else running is
    not an approximation at all: the only floating profit an account has at
    that moment belongs to positions that are open, and there are none.
    """
    by_account: dict[int, list[Trade]] = {}
    for trade in trades:
        if trade.opened_at is not None:
            by_account.setdefault(trade.account_id, []).append(trade)

    out: dict[int, float] = {}
    for account_id, rows in by_account.items():
        samples = [
            (when, equity)
            for when, equity in db.execute(
                select(EquityPoint.time, EquityPoint.equity)
                .where(EquityPoint.account_id == account_id)
                .order_by(EquityPoint.time)
            )
            if when is not None and equity
        ]
        timeline = _money_timeline(db, account_id)
        times = [when for when, _ in samples]

        for trade in rows:
            when = trade.opened_at
            found = _nearest_sample(samples, times, when)
            if found is not None:
                out[trade.id] = round(found, 2)
                continue
            worth = _worth_at(timeline, when)
            if worth is not None:
                out[trade.id] = round(worth, 2)
    return out


#: How far from a trade's open a recorded sample may be and still be taken as
#: that trade's equity. Terminals report every poll, so in practice this is
#: sub-second; the tolerance is for a heartbeat that was missed rather than
#: for guessing across a gap.
SAMPLE_TOLERANCE = timedelta(minutes=5)


def _nearest_sample(
    samples: list[tuple[datetime, float]], times: list[datetime], when: datetime
) -> float | None:
    if not samples:
        return None
    index = bisect_left(times, when)
    best: tuple[timedelta, float] | None = None
    for candidate in (index - 1, index):
        if 0 <= candidate < len(samples):
            gap = abs(samples[candidate][0] - when)
            if gap <= SAMPLE_TOLERANCE and (best is None or gap < best[0]):
                best = (gap, samples[candidate][1])
    return best[1] if best else None


def _worth_at(timeline: list[tuple[datetime, float]], when: datetime) -> float | None:
    """The reconstruction, read at a moment rather than at an event."""
    if not timeline:
        return None
    index = bisect_left([point[0] for point in timeline], when)
    if index < len(timeline):
        return timeline[index][1]
    return timeline[-1][1]


def cash_flows(
    db: Session, account_id: int | None, start: date, end: date
) -> list[dict[str, Any]]:
    """Money in and out of the account in this window, oldest first.

    Three kinds, kept apart because they answer different questions. A deposit
    is money paid in and a withdrawal is money taken out. An *adjustment* is
    neither: this broker writes debt off by moving it out of credit and into
    the balance, one deal on each side, to the cent and to the second -- twenty
    of them here, every one paired. It does raise what the account is worth,
    since credit cannot be withdrawn and cash can, but nobody funded anything
    and calling it a deposit would say they had. Left out of the funding total
    on this installation, that is 78.02 of "deposits" that were not.

    Credit itself never appears: it moves the broker's balance and it is not
    the account's money.

    Never counted as performance anywhere. This is here so the equity line can
    say why it stepped, and so a period can show what was paid in against what
    the trading did with it.
    """
    if account_id is None:
        return []
    window = (
        Deal.time >= datetime.combine(start, datetime.min.time()),
        Deal.time <= datetime.combine(end, datetime.max.time()),
    )
    rows = db.execute(
        select(Deal.time, Deal.profit)
        .where(Deal.account_id == account_id, Deal.deal_type == DEAL_TYPE_BALANCE, *window)
        .order_by(Deal.time)
    )
    credits = [
        (when, float(amount or 0.0))
        for when, amount in db.execute(
            select(Deal.time, Deal.profit).where(
                Deal.account_id == account_id, Deal.deal_type == DEAL_TYPE_CREDIT, *window
            )
        )
        if when is not None
    ]

    def offsets_a_credit(when: datetime, amount: float) -> bool:
        """Is this the other half of a credit movement rather than funding?"""
        return any(
            abs(amount + credit) < 0.005 and abs((when - at).total_seconds()) <= 5
            for at, credit in credits
        )

    out: list[dict[str, Any]] = []
    for when, raw in rows:
        if when is None or not raw:
            continue
        amount = round(float(raw), 2)
        if offsets_a_credit(when, amount):
            kind = "adjustment"
        else:
            kind = "deposit" if amount > 0 else "withdrawal"
        out.append({"time": when, "date": when.date(), "amount": amount, "kind": kind})
    return out
