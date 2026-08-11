"""Pydantic request/response models."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- clocks -----------------------------------------------------------------
#
# Two of them, stored in columns that look identical.
#
# One is ours: when a terminal last reported, when a copy was placed, when the
# user last logged in. Those are real moments, recorded from this machine's
# clock in UTC.
#
# The other is the broker's. MetaTrader keeps one clock -- its server's -- and
# every deal, execution and candle is stamped with it and with no offset, which
# for a typical broker is two or three hours from UTC. Nothing in the payload
# says which; only the account's `broker_utc_offset_minutes` can turn one into
# a real moment.
#
# SQLite hands both back as naive datetimes, and a naive timestamp in JSON is
# read by every browser as *local* time. For the broker's clock that is the
# behaviour we want -- the digits are passed through and read back unchanged,
# so a fill shows at the time the terminal shows it, wherever it is opened.
# For ours it is a bug: a UTC instant read as local made a terminal that had
# reported five seconds ago show up as "quiet 2 hours ago" for anyone sitting
# east of UTC, and -- worse, because it is silent -- made a genuinely dead
# terminal look healthy for anyone sitting west of it.
#
# So the two are spelled differently from here on, and which clock a field is
# on is part of its type rather than something to work out from its name.


def _mark_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


#: A moment on our clock, serialised with its offset so a browser reads it as
#: the instant it is rather than as local wall clock.
ServerTime = Annotated[datetime, AfterValidator(_mark_utc)]

#: A reading off the broker's clock, passed through exactly as MetaTrader
#: wrote it. Deliberately naive: there is no offset to attach that would be
#: true for every account.
BrokerTime = datetime


# --- auth -------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)
    remember: bool = True


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=72)


class UserOut(ORMModel):
    id: int
    username: str
    last_login_at: ServerTime | None = None


# --- tags -------------------------------------------------------------------


class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    color: str = Field(default="#7c8cf8", max_length=16)
    category: str = Field(default="custom", max_length=24)
    sort_order: int = 0


class TagOut(ORMModel):
    id: int
    name: str
    color: str
    category: str
    sort_order: int


# --- trades -----------------------------------------------------------------


class ExecutionOut(ORMModel):
    id: int
    ticket: int
    kind: str
    side: str
    volume: float
    price: float
    time: BrokerTime
    profit: float
    commission: float
    swap: float


class TradeOut(ORMModel):
    #: Balance just before this trade closed, and its result as a share of it.
    #: Computed per request from everything that closed earlier, so it is never
    #: stored and never stale.
    balance_before: float | None = None
    return_pct: float | None = None
    id: int
    account_id: int
    position_id: int
    symbol: str
    direction: str
    opened_at: BrokerTime
    closed_at: BrokerTime | None
    trade_date: date | None
    volume: float
    closed_volume: float
    entry_price: float
    exit_price: float | None
    gross_profit: float
    commission: float
    swap: float
    fee: float
    net_pnl: float
    value_per_unit: float
    digits: int
    initial_stop: float | None
    initial_target: float | None
    stop_source: str
    target_source: str
    risk_override: float | None
    risk_amount: float | None
    planned_r: float | None
    realized_r: float | None
    outcome: str
    duration_seconds: int | None
    notes: str
    setup: str
    rating: int | None
    excluded: bool
    source: str
    magic: int
    comment: str
    is_manual: bool
    tags: list[TagOut] = []


class TradeDetailOut(TradeOut):
    executions: list[ExecutionOut] = []


class TradeUpdate(BaseModel):
    notes: str | None = None
    setup: str | None = Field(default=None, max_length=120)
    rating: int | None = Field(default=None, ge=1, le=5)
    excluded: bool | None = None
    initial_stop: float | None = None
    initial_target: float | None = None
    risk_override: float | None = None
    tag_ids: list[int] | None = None
    # Explicitly clear a manual override and fall back to the broker value.
    reset_stop: bool = False
    reset_target: bool = False
    reset_risk: bool = False


class ManualTradeIn(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    direction: str = Field(pattern="^(long|short)$")
    opened_at: datetime
    closed_at: datetime | None = None
    volume: float = Field(gt=0)
    entry_price: float = Field(gt=0)
    exit_price: float | None = None
    gross_profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    fee: float = 0.0
    initial_stop: float | None = None
    initial_target: float | None = None
    risk_override: float | None = None
    value_per_unit: float = 0.0
    notes: str = ""
    setup: str = ""
    rating: int | None = Field(default=None, ge=1, le=5)
    tag_ids: list[int] = []
    account_id: int | None = None


class BulkTagRequest(BaseModel):
    trade_ids: list[int]
    add_tag_ids: list[int] = []
    remove_tag_ids: list[int] = []
    excluded: bool | None = None


class TradePage(BaseModel):
    items: list[TradeOut]
    total: int
    page: int
    page_size: int
    totals: dict[str, Any]


# --- MT5 ingest -------------------------------------------------------------


class MT5AccountInfo(BaseModel):
    login: str
    name: str = ""
    server: str = ""
    company: str = ""
    currency: str = "USD"
    leverage: int = 0
    balance: float = 0.0
    equity: float = 0.0
    #: The broker's own clock, as a Unix epoch -- see services.brokerclock.
    server_time: int | None = None

    @field_validator("login", mode="before")
    @classmethod
    def _stringify(cls, value: Any) -> str:
        return str(value)


class MT5Deal(BaseModel):
    ticket: int
    order: int = 0
    position_id: int = 0
    symbol: str = ""
    type: int = 0
    entry: int = 0
    volume: float = 0.0
    price: float = 0.0
    profit: float = 0.0
    commission: float = 0.0
    swap: float = 0.0
    fee: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    magic: int = 0
    comment: str = ""
    time: Any
    value_per_unit: float = 0.0
    digits: int = 5


class MT5Candle(BaseModel):
    time: Any
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


class MT5CandleBatch(BaseModel):
    symbol: str
    timeframe: str = "M15"
    candles: list[MT5Candle] = []


class MT5IngestRequest(BaseModel):
    account: MT5AccountInfo
    deals: list[MT5Deal] = []
    candles: list[MT5CandleBatch] = []
    # Set by the EA on its first push so the server knows history is complete.
    full_history: bool = False


class MT5IngestResponse(BaseModel):
    ok: bool = True
    account_id: int
    deals_received: int
    deals_new: int
    trades_upserted: int
    candles_stored: int = 0
    last_deal_ticket: int = 0
    message: str = ""


class MT5CredentialsIn(BaseModel):
    server: str = Field(min_length=1, max_length=120)
    login: str = Field(min_length=1, max_length=64)
    # Omit to keep the stored password; send "" to clear it.
    password: str | None = Field(default=None, max_length=200)

    @field_validator("login", mode="before")
    @classmethod
    def _stringify_login(cls, value: Any) -> str:
        return str(value)


class MT5CredentialsOut(BaseModel):
    """Never carries the password, only whether one is stored and usable."""

    configured: bool
    server: str
    login: str
    password_readable: bool


class SyncStatus(BaseModel):
    account_id: int | None
    login: str | None
    name: str | None
    balance: float | None
    equity: float | None
    currency: str | None
    last_sync_at: ServerTime | None
    last_sync_source: str | None
    total_deals: int
    total_trades: int
    open_trades: int
    sync_mode: str
    #: Whether a terminal has reported in recently. None when sync is off.
    connected: bool | None = None
    #: off | no-account | starting | connected | stalled. Lets the UI say
    #: "starting" instead of leaving a blank screen while a terminal is built.
    phase: str = "off"
    credentials_configured: bool = False
    message: str = ""


# --- notes / settings -------------------------------------------------------


class DayNoteIn(BaseModel):
    day: date
    content: str = ""
    mood: str = Field(default="", max_length=24)


class DayNoteOut(ORMModel):
    id: int
    day: date
    content: str
    mood: str


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="allow")


class AccountIn(BaseModel):
    name: str | None = None
    initial_balance: float | None = None
    currency: str | None = None
    is_default: bool | None = None


class AccountOut(ORMModel):
    id: int
    login: str
    name: str
    broker: str
    server: str
    currency: str
    leverage: int
    balance: float
    equity: float
    initial_balance: float
    is_default: bool
    last_sync_at: ServerTime | None
    last_sync_source: str
    #: How far this broker's clock runs from UTC; None until a terminal says.
    broker_utc_offset_minutes: int | None = None


class CandleOut(BaseModel):
    time: BrokerTime
    open: float
    high: float
    low: float
    close: float
    volume: float


class CandleResponse(BaseModel):
    symbol: str
    timeframe: str
    candles: list[CandleOut]
    #: "local" for bars a terminal actually sent at this timeframe, or the
    #: timeframe they were built from -- so the chart can say so rather than
    #: implying the broker drew it that way.
    source: str = "local"
    #: Timeframes this symbol can be drawn at, given what has been collected.
    #: Everything above the collected one is arithmetic; nothing below it
    #: exists, and offering a button that can only ever be empty is worse than
    #: not offering it.
    available: list[str] = []


# --- copier -----------------------------------------------------------------


class CopySettingsOut(BaseModel):
    """The whole per-slave rule set, flat so a form can bind to it directly."""

    model_config = ConfigDict(extra="allow")

    mode: str = "balance_ratio"
    multiplier: float = 1.0
    fixed_lot: float = 0.01
    risk_percent: float = 1.0
    max_lot: float = 0.0
    min_lot: float = 0.0
    scale: float = 1.0
    mirror_stops: bool = True

    max_risk_percent_per_trade: float = 0.0
    max_lot_per_trade: float = 0.0
    require_stop_loss: bool = False
    #: Points, one unit of the last digit the broker quotes. 0 disables.
    min_stop_distance_points: float = 0.0
    max_open_positions: int = 0
    max_same_direction: int = 0
    max_positions_per_symbol: int = 0
    max_total_lots: float = 0.0

    max_daily_drawdown_percent: float = 0.0
    equity_stop_percent: float = 0.0
    equity_stop_amount: float = 0.0
    breach_action: str = "close_all"

    take_profit_at_amount: float = 0.0
    take_profit_at_r: float = 0.0
    daily_profit_target_percent: float = 0.0
    max_day_share_of_profit_percent: float = 0.0

    allowed_symbols: list[str] = Field(default_factory=list)
    blocked_symbols: list[str] = Field(default_factory=list)


class SlaveAccountIn(BaseModel):
    login: str = Field(default="", max_length=64)
    server: str = Field(default="", max_length=120)
    name: str = Field(default="", max_length=120)
    broker: str = Field(default="", max_length=120)
    currency: str = Field(default="USD", max_length=8)
    # Omit to keep the stored password; "" clears it and disarms the account.
    password: str | None = Field(default=None, max_length=200)
    symbol_prefix: str = Field(default="", max_length=16)
    symbol_suffix: str = Field(default="", max_length=16)
    symbol_map: dict[str, str] = Field(default_factory=dict)
    settings: dict[str, Any] | None = None

    @field_validator("login", mode="before")
    @classmethod
    def _stringify_login(cls, value: Any) -> str:
        return "" if value is None else str(value)


class SlaveAccountOut(BaseModel):
    id: int
    login: str
    name: str
    broker: str
    server: str
    currency: str
    role: str
    balance: float
    equity: float
    is_default: bool
    last_sync_at: ServerTime | None
    #: How far this broker's clock runs from UTC; None until a terminal says.
    broker_utc_offset_minutes: int | None = None
    #: What the provisioner last reported this terminal was doing.
    terminal_state: dict[str, Any] = Field(default_factory=dict)

    copy_enabled: bool
    copy_dry_run: bool
    copy_halted: bool
    copy_halt_reason: str
    copy_halted_at: ServerTime | None
    has_password: bool

    symbol_prefix: str
    symbol_suffix: str
    symbol_map: dict[str, str]
    #: What the copier worked out for itself, master symbol -> this broker's
    #: name for it. Shown so the mapping is something you can check, not
    #: something you have to trust.
    symbol_learned: dict[str, str] = Field(default_factory=dict)
    settings: CopySettingsOut
    open_copies: int


class SymbolMappingIn(BaseModel):
    """Correcting, or forgetting, how a slave names an instrument."""

    #: Master symbol -> the name to use on this slave. Replaces the whole set.
    overrides: dict[str, str] = Field(default_factory=dict)
    #: Master symbols whose remembered match should be worked out again, for
    #: when the copier picked something and the broker has since changed it.
    forget: list[str] = Field(default_factory=list)


class SlaveArmIn(BaseModel):
    enabled: bool
    dry_run: bool = True


class CopyEventOut(ORMModel):
    id: int
    slave_account_id: int | None
    master_position_id: int
    action: str
    outcome: str
    symbol: str
    direction: str
    volume: float
    price: float
    rule: str
    message: str
    latency_ms: int
    created_at: ServerTime


# --- expert advisor agent ---------------------------------------------------


class AgentPosition(BaseModel):
    """One open position as the terminal sees it."""

    position_id: int = 0
    ticket: int = 0
    symbol: str = ""
    direction: str = "long"
    volume: float = 0.0
    open_price: float = 0.0
    stop_loss: float | None = None
    take_profit: float | None = None
    profit: float = 0.0


class AgentSymbol(BaseModel):
    """Contract details, so sizing can be worked out for this broker."""

    symbol: str
    volume_min: float = 0.01
    volume_max: float = 100.0
    volume_step: float = 0.01
    value_per_unit: float = 0.0
    digits: int = 5


class AgentCommandResult(BaseModel):
    id: str = ""
    account_id: int = 0
    action: str = ""
    ok: bool = False
    ticket: int = 0
    master_position_id: int = 0
    symbol: str = ""
    direction: str = ""
    volume: float = 0.0
    price: float = 0.0
    retcode: int = 0
    message: str = ""


class AgentPollIn(BaseModel):
    login: str = ""
    server: str = ""
    name: str = ""
    currency: str = ""
    balance: float = 0.0
    equity: float = 0.0
    margin_free: float = 0.0
    #: The broker's own clock, as a Unix epoch. Used to work out how far it
    #: runs from UTC -- see services.brokerclock.
    server_time: int | None = None
    trade_allowed: bool = True
    positions: list[AgentPosition] = Field(default_factory=list)
    symbols: list[AgentSymbol] = Field(default_factory=list)
    results: list[AgentCommandResult] = Field(default_factory=list)

    @field_validator("login", mode="before")
    @classmethod
    def _stringify_login(cls, value: Any) -> str:
        return "" if value is None else str(value)


class TerminalStateIn(BaseModel):
    """One terminal, as the provisioner currently sees it."""

    account_id: int
    #: installing | starting | retrying | running | quiet | failed
    phase: str = Field(default="", max_length=24)
    message: str = Field(default="", max_length=400)
    attempts: int = 0


class TerminalStatesIn(BaseModel):
    terminals: list[TerminalStateIn] = Field(default_factory=list)


class AgentPollOut(BaseModel):
    account_id: int
    role: str
    enabled: bool
    dry_run: bool
    halted: bool
    poll_seconds: int = 5
    #: How much history to send around each closed trade, in seconds either
    #: side. Seconds rather than a bar count so the terminal can divide by
    #: whatever timeframe it is set to collect, and so changing the setting
    #: takes effect on the next heartbeat instead of at the next restart.
    history_before_seconds: int = 86_400
    history_after_seconds: int = 86_400
    #: Which timeframe to collect, as the length of one bar in seconds. Sent
    #: rather than named so the terminal does not have to agree with this
    #: server about spelling.
    candle_seconds: int = 300
    commands: list[dict[str, Any]] = Field(default_factory=list)
