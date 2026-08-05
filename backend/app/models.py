"""SQLAlchemy ORM models for TradeZulu."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON}


@event.listens_for(Base, "init", propagate=True)
def _apply_scalar_defaults(target, _args, kwargs) -> None:
    """Give freshly constructed objects their column defaults immediately.

    SQLAlchemy normally only applies defaults at INSERT time, which means a
    transient row has ``None`` where the schema says ``0.0``. Statistics code
    then trips over ``None + float``, so we fill scalar defaults up front.
    """
    for column in target.__table__.columns:
        default = column.default
        if default is None or column.key in kwargs or not default.is_scalar:
            continue
        kwargs[column.key] = default.arg


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Bumped on password change so existing sessions are invalidated.
    token_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Account(Base):
    """A broker account: the master you trade, or a slave that follows it."""

    __tablename__ = "account"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    login: Mapped[str] = mapped_column(String(64), nullable=False)
    # master | slave | standalone. Exactly one master copies to N slaves.
    role: Mapped[str] = mapped_column(String(16), default="master", index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    broker: Mapped[str] = mapped_column(String(120), default="")
    server: Mapped[str] = mapped_column(String(120), default="")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    leverage: Mapped[int] = mapped_column(Integer, default=0)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    equity: Mapped[float] = mapped_column(Float, default=0.0)
    # Starting balance used for percentage based metrics; 0 => infer.
    initial_balance: Mapped[float] = mapped_column(Float, default=0.0)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # How far the broker's clock runs from UTC, in minutes. Every timestamp
    # MetaTrader reports -- deals, candles, everything -- is on the broker's
    # server clock and carries no offset with it, so this is the only thing
    # that can turn one into a real moment. NULL means no terminal has told us
    # yet, and times are shown as the broker wrote them.
    broker_utc_offset_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # What the provisioner last said this account's terminal was doing:
    # {"phase", "message", "attempts", "at"}. The provisioner is the only thing
    # that can tell installing from starting from given-up, and without this it
    # kept that to itself -- so a terminal that was still building MetaTrader
    # and one that had been abandoned twenty minutes ago read identically.
    terminal_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_sync_source: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # --- copier ---------------------------------------------------------
    # Slaves start disabled and in dry-run: nothing reaches a broker until
    # both are deliberately turned on, one account at a time.
    copy_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    copy_dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    # Set when a guard trips; cleared by the user or at the next trading day.
    copy_halted: Mapped[bool] = mapped_column(Boolean, default=False)
    copy_halt_reason: Mapped[str] = mapped_column(String(255), default="")
    copy_halted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Sizing and risk settings, shaped like SizingConfig and RiskConfig.
    copy_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # A slave needs a trade-enabled password; an investor one cannot place
    # orders. Encrypted at rest with the same key as the master's.
    password_enc: Mapped[str] = mapped_column(Text, default="")
    # Broker symbol differences: suffix/prefix plus explicit overrides.
    symbol_suffix: Mapped[str] = mapped_column(String(16), default="")
    symbol_prefix: Mapped[str] = mapped_column(String(16), default="")
    symbol_map: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Master symbol -> this broker's name for it, as worked out on the way past.
    # Not the user's: symbol_map is theirs and always wins. Kept so the search
    # runs once per instrument rather than on every position change, and so
    # what the copier decided is something you can look at.
    symbol_learned: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Equity at the start of the current trading day, for the daily guards.
    day_start_equity: Mapped[float] = mapped_column(Float, default=0.0)
    day_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    peak_equity: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (UniqueConstraint("login", "server", name="uq_account_login_server"),)

    trades: Mapped[list[Trade]] = relationship(back_populates="account")


class Deal(Base):
    """Raw MT5 deal rows. Kept so trades can always be re-aggregated."""

    __tablename__ = "deal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("account.id", ondelete="CASCADE"))
    ticket: Mapped[int] = mapped_column(Integer, nullable=False)
    order_id: Mapped[int] = mapped_column(Integer, default=0)
    position_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    symbol: Mapped[str] = mapped_column(String(32), default="")
    # 0 = buy, 1 = sell, 2 = balance, ... (DEAL_TYPE_*)
    deal_type: Mapped[int] = mapped_column(Integer, default=0)
    # 0 = in, 1 = out, 2 = inout, 3 = out_by (DEAL_ENTRY_*)
    entry: Mapped[int] = mapped_column(Integer, default=0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    profit: Mapped[float] = mapped_column(Float, default=0.0)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    swap: Mapped[float] = mapped_column(Float, default=0.0)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    sl: Mapped[float] = mapped_column(Float, default=0.0)
    tp: Mapped[float] = mapped_column(Float, default=0.0)
    magic: Mapped[int] = mapped_column(Integer, default=0)
    comment: Mapped[str] = mapped_column(String(255), default="")
    time: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # Money value of one full price unit for one lot (tick_value / tick_size).
    value_per_unit: Mapped[float] = mapped_column(Float, default=0.0)
    digits: Mapped[int] = mapped_column(Integer, default=5)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("account_id", "ticket", name="uq_deal_account_ticket"),
        Index("ix_deal_account_time", "account_id", "time"),
    )


class Tag(Base):
    __tablename__ = "tag"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#7c8cf8")
    # mistake | setup | emotion | custom
    category: Mapped[str] = mapped_column(String(24), default="custom")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    trades: Mapped[list[Trade]] = relationship(
        secondary="trade_tag", back_populates="tags", lazy="selectin"
    )


class TradeTag(Base):
    __tablename__ = "trade_tag"

    trade_id: Mapped[int] = mapped_column(
        ForeignKey("trade.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id", ondelete="CASCADE"), primary_key=True)


class Trade(Base):
    """One position: every deal sharing an MT5 position_id, aggregated."""

    __tablename__ = "trade"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), index=True
    )
    position_id: Mapped[int] = mapped_column(Integer, default=0, index=True)

    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(5), nullable=False)  # long | short

    opened_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    # Local trading date of the close (or open, while running), used by the calendar.
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    volume: Mapped[float] = mapped_column(Float, default=0.0)
    closed_volume: Mapped[float] = mapped_column(Float, default=0.0)
    entry_price: Mapped[float] = mapped_column(Float, default=0.0)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)

    gross_profit: Mapped[float] = mapped_column(Float, default=0.0)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    swap: Mapped[float] = mapped_column(Float, default=0.0)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl: Mapped[float] = mapped_column(Float, default=0.0)

    # Money per 1.0 of price movement, for one lot.
    value_per_unit: Mapped[float] = mapped_column(Float, default=0.0)
    digits: Mapped[int] = mapped_column(Integer, default=5)

    # Plan -------------------------------------------------------------
    initial_stop: Mapped[float | None] = mapped_column(Float, nullable=True)
    initial_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_source: Mapped[str] = mapped_column(String(16), default="none")  # mt5|manual|none
    target_source: Mapped[str] = mapped_column(String(16), default="none")
    # Manual override of the dollar risk; wins over the stop-derived value.
    risk_override: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Derived (recomputed whenever inputs or settings change) -------------
    risk_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    planned_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    # win | loss | breakeven | open
    outcome: Mapped[str] = mapped_column(String(12), default="open", index=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Journal ------------------------------------------------------------
    notes: Mapped[str] = mapped_column(Text, default="")
    setup: Mapped[str] = mapped_column(String(120), default="")
    rating: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1..5
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)

    # Provenance ----------------------------------------------------------
    source: Mapped[str] = mapped_column(String(16), default="mt5")
    magic: Mapped[int] = mapped_column(Integer, default=0)
    comment: Mapped[str] = mapped_column(String(255), default="")
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    account: Mapped[Account] = relationship(back_populates="trades")
    tags: Mapped[list[Tag]] = relationship(
        secondary="trade_tag", back_populates="trades", lazy="selectin"
    )
    executions: Mapped[list[Execution]] = relationship(
        back_populates="trade", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        UniqueConstraint("account_id", "position_id", name="uq_trade_account_position"),
        Index("ix_trade_account_closed", "account_id", "closed_at"),
    )


class Execution(Base):
    """A single fill inside a trade — used for the entry/exit markers on charts."""

    __tablename__ = "execution"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_id: Mapped[int] = mapped_column(ForeignKey("trade.id", ondelete="CASCADE"), index=True)
    ticket: Mapped[int] = mapped_column(Integer, default=0)
    kind: Mapped[str] = mapped_column(String(8), default="in")  # in | out
    side: Mapped[str] = mapped_column(String(4), default="buy")  # buy | sell
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    profit: Mapped[float] = mapped_column(Float, default=0.0)
    commission: Mapped[float] = mapped_column(Float, default=0.0)
    swap: Mapped[float] = mapped_column(Float, default=0.0)

    trade: Mapped[Trade] = relationship(back_populates="executions")


class Candle(Base):
    """Cached OHLC used by the local chart replay."""

    __tablename__ = "candle"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)  # M1, M5, M15, H1, ...
    time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    open: Mapped[float] = mapped_column(Float, default=0.0)
    high: Mapped[float] = mapped_column(Float, default=0.0)
    low: Mapped[float] = mapped_column(Float, default=0.0)
    close: Mapped[float] = mapped_column(Float, default=0.0)
    volume: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "time", name="uq_candle_key"),
        Index("ix_candle_lookup", "symbol", "timeframe", "time"),
    )


class DayNote(Base):
    __tablename__ = "day_note"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="")
    mood: Mapped[str] = mapped_column(String(24), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Setting(Base):
    __tablename__ = "setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CopyLink(Base):
    """One copied position: which slave trade mirrors which master trade."""

    __tablename__ = "copy_link"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slave_account_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), index=True
    )
    master_position_id: Mapped[int] = mapped_column(Integer, index=True)
    slave_position_id: Mapped[int] = mapped_column(Integer, default=0, index=True)

    symbol: Mapped[str] = mapped_column(String(32), default="")
    slave_symbol: Mapped[str] = mapped_column(String(32), default="")
    direction: Mapped[str] = mapped_column(String(5), default="long")
    master_volume: Mapped[float] = mapped_column(Float, default=0.0)
    slave_volume: Mapped[float] = mapped_column(Float, default=0.0)
    open_price: Mapped[float] = mapped_column(Float, default=0.0)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Float, nullable=True)

    # open | closed | failed | skipped
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    sizing_reason: Mapped[str] = mapped_column(String(255), default="")
    close_reason: Mapped[str] = mapped_column(String(255), default="")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)

    opened_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "slave_account_id", "master_position_id", name="uq_copy_link_slave_master"
        ),
    )


class CopyEvent(Base):
    """The copier's audit trail. Every decision, taken or refused."""

    __tablename__ = "copy_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slave_account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    master_position_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # open | close | modify | skip | halt | resume | error
    action: Mapped[str] = mapped_column(String(16), default="open", index=True)
    # ok | skipped | halted | failed | dry_run
    outcome: Mapped[str] = mapped_column(String(16), default="ok", index=True)
    symbol: Mapped[str] = mapped_column(String(32), default="")
    direction: Mapped[str] = mapped_column(String(5), default="")
    volume: Mapped[float] = mapped_column(Float, default=0.0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    #: The rule that refused it, when one did.
    rule: Mapped[str] = mapped_column(String(64), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    __table_args__ = (Index("ix_copy_event_account_time", "slave_account_id", "created_at"),)


class EquityPoint(Base):
    """Periodic balance/equity samples, so every account has a real curve."""

    __tablename__ = "equity_point"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("account.id", ondelete="CASCADE"), index=True
    )
    time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    balance: Mapped[float] = mapped_column(Float, default=0.0)
    equity: Mapped[float] = mapped_column(Float, default=0.0)
    open_positions: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("account_id", "time", name="uq_equity_point"),
        Index("ix_equity_account_time", "account_id", "time"),
    )


class SyncLog(Base):
    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(24), default="")
    status: Mapped[str] = mapped_column(String(16), default="ok")
    deals_received: Mapped[int] = mapped_column(Integer, default=0)
    deals_new: Mapped[int] = mapped_column(Integer, default=0)
    trades_upserted: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
