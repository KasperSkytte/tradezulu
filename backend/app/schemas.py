"""Pydantic request/response models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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
    last_login_at: datetime | None = None


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
    time: datetime
    profit: float
    commission: float
    swap: float


class TradeOut(ORMModel):
    id: int
    account_id: int
    position_id: int
    symbol: str
    direction: str
    opened_at: datetime
    closed_at: datetime | None
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
    last_sync_at: datetime | None
    last_sync_source: str | None
    total_deals: int
    total_trades: int
    open_trades: int
    sync_mode: str
    #: Whether a terminal has reported in recently. None when sync is off.
    connected: bool | None = None
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
    last_sync_at: datetime | None
    last_sync_source: str


class CandleOut(BaseModel):
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class CandleResponse(BaseModel):
    symbol: str
    timeframe: str
    candles: list[CandleOut]
    source: str = "local"


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
    last_sync_at: datetime | None

    copy_enabled: bool
    copy_dry_run: bool
    copy_halted: bool
    copy_halt_reason: str
    copy_halted_at: datetime | None
    has_password: bool

    symbol_prefix: str
    symbol_suffix: str
    symbol_map: dict[str, str]
    settings: CopySettingsOut
    open_copies: int


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
    created_at: datetime


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
    trade_allowed: bool = True
    positions: list[AgentPosition] = Field(default_factory=list)
    symbols: list[AgentSymbol] = Field(default_factory=list)
    results: list[AgentCommandResult] = Field(default_factory=list)

    @field_validator("login", mode="before")
    @classmethod
    def _stringify_login(cls, value: Any) -> str:
        return "" if value is None else str(value)


class AgentPollOut(BaseModel):
    account_id: int
    role: str
    enabled: bool
    dry_run: bool
    halted: bool
    poll_seconds: int = 5
    commands: list[dict[str, Any]] = Field(default_factory=list)
