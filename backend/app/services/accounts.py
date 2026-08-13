"""Removing an account and everything filed under it.

Forgetting an account has to mean forgetting it. Clearing the credentials and
leaving the trades behind is the worst of both: the account is gone from the
interface, its history still counts towards every total, and re-adding the same
number silently inherits it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import Account, CopyEvent, CopyLink, Deal, EquityPoint, Trade


def single_master(db: Session) -> Account | None:
    """Leave exactly one account holding the master role, and return it.

    Exactly one includes the case of none. A fresh install is given a
    placeholder master to adopt, but Forget deletes it, and the placeholder is
    only ever created on an empty database -- so on an install that also has a
    slave, entering credentials again left the master with nowhere to land.
    The interface said the account was configured, the provisioner was never
    told to start a terminal for it, and nothing anywhere said why.

    There is only ever one account trades are copied *from*, and until now
    nothing enforced that. The role column defaults to "master", and two paths
    created accounts without saying otherwise -- a terminal reporting a login
    nobody had configured, and a statement dropped on the import page -- so an
    install could end up with several. That is not a cosmetic problem: Forget
    removes whichever one the query returns first, and the rest were refused
    by the accounts endpoint for being masters, so they could not be removed
    at all.

    Which one keeps the role is not arbitrary. The master is the account whose
    credentials are stored, because that is the account a terminal is started
    for; failing that, the default account, and failing that the oldest. The
    others become archived: they keep every trade, they are still in the
    journal, and they can be deleted like anything else.
    """
    from .credentials import credentials_status

    stored = credentials_status(db)
    masters = list(db.scalars(select(Account).where(Account.role == "master")))

    if not masters:
        if not stored.get("login"):
            return None
        # Named after the account it is for rather than "Default account":
        # this one is not a placeholder waiting to be filled in, it is the
        # account whose credentials have just been stored.
        master = Account(
            login=str(stored.get("login") or ""),
            server=str(stored.get("server") or ""),
            name=f"Account {stored.get('login')}",
            currency="USD",
            role="master",
            is_default=db.scalar(select(Account.id).where(Account.is_default)) is None,
        )
        db.add(master)
        db.flush()
        return master

    if len(masters) == 1:
        return masters[0]

    wanted = str(stored.get("login") or "").strip()
    keep = next((a for a in masters if a.login.strip() == wanted and wanted), None)
    keep = keep or next((a for a in masters if a.is_default), None) or masters[0]

    for account in masters:
        if account is keep:
            continue
        account.role = "archived"
        account.copy_enabled = False
    db.flush()
    return keep


def account_contents(db: Session, account: Account) -> dict[str, int]:
    """How much is filed under this account, for a confirmation that means something.

    "Delete 2,085 trades" is a decision. "Forget the stored account" is not.
    """
    def count(model: Any, column: Any) -> int:
        return int(db.scalar(select(func.count()).select_from(model).where(column == account.id)) or 0)

    return {
        "trades": count(Trade, Trade.account_id),
        "deals": count(Deal, Deal.account_id),
        "equity_points": count(EquityPoint, EquityPoint.account_id),
        "copy_links": count(CopyLink, CopyLink.slave_account_id),
        "copy_events": count(CopyEvent, CopyEvent.slave_account_id),
    }


def purge_account(db: Session, account: Account) -> dict[str, int]:
    """Delete the account and every row that belongs to it.

    Deals, trades (and their executions), equity samples and copy links go by
    the foreign key's own cascade. Copy events do not: the column that names
    the account is a plain integer with no constraint behind it, so those rows
    would survive as orphans pointing at an id nobody can resolve. They are
    removed here explicitly.

    Candles and day notes are deliberately left. A candle is priced by symbol
    and shared by every account that traded it, and a note is attached to a day
    rather than to an account -- neither is this account's to take with it.
    """
    removed = account_contents(db, account)
    account_id = account.id

    # Issued as statements rather than through the ORM. Deleting the Account
    # object makes SQLAlchemy "de-associate" the trades it has loaded -- it sets
    # trade.account_id to NULL, which the column forbids, and the delete fails
    # before the database's own cascade is ever reached. A DELETE statement goes
    # straight to SQLite, where the foreign keys do the work (executions follow
    # their trades from there).
    for model, column in (
        (Deal, Deal.account_id),
        (Trade, Trade.account_id),
        (EquityPoint, EquityPoint.account_id),
        (CopyLink, CopyLink.slave_account_id),
        # No foreign key behind this column, so nothing would remove these.
        (CopyEvent, CopyEvent.slave_account_id),
    ):
        db.execute(delete(model).where(column == account_id))

    db.execute(delete(Account).where(Account.id == account_id))
    # The session still holds rows that no longer exist.
    db.expire_all()

    # Something has to be the default, or every unscoped figure loses its
    # balance. The oldest survivor is as good a choice as any and beats none.
    if not db.scalar(select(Account).where(Account.is_default.is_(True))):
        survivor = db.scalar(select(Account).order_by(Account.id))
        if survivor is not None:
            survivor.is_default = True

    return removed
