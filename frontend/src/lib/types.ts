export type Outcome = 'win' | 'loss' | 'breakeven' | 'open'
export type Direction = 'long' | 'short'

export interface Tag {
  id: number
  name: string
  color: string
  category: 'setup' | 'mistake' | 'emotion' | 'custom'
  sort_order: number
}

export interface Execution {
  id: number
  ticket: number
  kind: 'in' | 'out'
  side: 'buy' | 'sell'
  volume: number
  price: number
  time: string
  profit: number
  commission: number
  swap: number
}

export interface Trade {
  id: number
  account_id: number
  position_id: number
  symbol: string
  direction: Direction
  opened_at: string
  closed_at: string | null
  trade_date: string | null
  volume: number
  closed_volume: number
  entry_price: number
  exit_price: number | null
  gross_profit: number
  commission: number
  swap: number
  fee: number
  net_pnl: number
  value_per_unit: number
  digits: number
  initial_stop: number | null
  initial_target: number | null
  stop_source: string
  target_source: string
  risk_override: number | null
  risk_amount: number | null
  planned_r: number | null
  realized_r: number | null
  outcome: Outcome
  duration_seconds: number | null
  notes: string
  setup: string
  rating: number | null
  excluded: boolean
  source: string
  magic: number
  comment: string
  is_manual: boolean
  tags: Tag[]
}

export interface TradeDetail extends Trade {
  executions: Execution[]
}

export interface TradePage {
  items: Trade[]
  total: number
  page: number
  page_size: number
  totals: {
    net_pnl: number
    total_r: number
    volume: number
    wins: number
    losses: number
    breakevens: number
  }
}

export interface ZuluScore {
  score: number
  components: {
    win_rate: number | null
    profit_factor: number | null
    avg_win_loss: number | null
    max_drawdown: number | null
    recovery_factor: number | null
    consistency: number | null
  }
  targets: Record<string, number>
  weights: Record<string, number>
  sample_size: number | null
  min_trades: number
  sufficient: boolean
}

export interface EquityPoint {
  trade_id: number
  time: string
  symbol: string
  net_pnl: number
  cum_pnl: number
  cum_r: number
  equity: number
  drawdown: number
}

export interface DailyPoint {
  date: string
  net_pnl: number
  trades: number
  wins: number
  losses: number
  breakevens: number
  r: number
  win_rate: number | null
  volume: number
  commission: number
  swap: number
  note?: string
  mood?: string
}

export interface Summary {
  period: { start: string | null; end: string | null }
  counts: {
    total: number
    scored: number
    wins: number
    losses: number
    breakevens: number
    open: number
    excluded: number
  }
  net_pnl: number | null
  scored_net_pnl: number | null
  gross_profit: number | null
  gross_loss: number | null
  commission: number | null
  swap: number | null
  breakeven_pnl: number | null
  breakeven_rate: number | null
  win_rate: number | null
  loss_rate: number | null
  avg_win: number | null
  avg_loss: number | null
  avg_trade: number | null
  payoff_ratio: number | null
  profit_factor: number | null
  expectancy: number | null
  largest_win: number | null
  largest_loss: number | null
  avg_win_r: number | null
  avg_loss_r: number | null
  expectancy_r: number | null
  total_r: number | null
  avg_planned_r: number | null
  avg_realized_r: number | null
  plan_adherence: number | null
  avg_risk: number | null
  max_drawdown: number | null
  max_drawdown_pct: number | null
  recovery_factor: number | null
  sharpe: number | null
  sortino: number | null
  kelly: number | null
  consistency: number | null
  volume: number | null
  streaks: { max_win_streak: number; max_loss_streak: number; current_streak: number }
  durations: { avg: number | null; avg_win: number | null; avg_loss: number | null }
  days: {
    total: number
    green: number
    red: number
    flat: number
    win_rate: number | null
    best: number | null
    worst: number | null
    avg: number | null
  }
  account_size: number | null
  zulu_score: ZuluScore
  equity_curve: EquityPoint[]
  daily: DailyPoint[]
}

export interface BreakdownRow {
  key: string
  trades: number
  wins: number
  losses: number
  breakevens: number
  net_pnl: number | null
  win_rate: number | null
  profit_factor: number | null
  total_r: number | null
  avg_r: number | null
  volume: number | null
}

export interface Breakdowns {
  by_symbol: BreakdownRow[]
  by_direction: BreakdownRow[]
  by_weekday: BreakdownRow[]
  by_hour: BreakdownRow[]
  by_duration: BreakdownRow[]
  by_r_multiple: BreakdownRow[]
  by_setup: BreakdownRow[]
  by_tag: BreakdownRow[]
}

export interface CalendarWeek {
  week_start: string
  net_pnl: number
  trades: number
  days: number
  r: number
}

export interface CalendarResponse {
  month: string
  start: string
  end: string
  days: DailyPoint[]
  weeks: CalendarWeek[]
  summary: Pick<
    Summary,
    'net_pnl' | 'win_rate' | 'profit_factor' | 'counts' | 'total_r' | 'days' | 'expectancy'
  >
}

export interface DayDetail {
  date: string
  summary: Omit<Summary, 'equity_curve' | 'daily'>
  equity_curve: EquityPoint[]
  trade_ids: number[]
  note: { content: string; mood: string } | null
}

export interface AppSettings {
  general: {
    timezone: string
    currency: string
    currency_symbol: string
    week_starts_on: 'monday' | 'sunday'
    default_period: string
    date_format: string
    theme: 'dark' | 'light' | 'system'
    accent: string
    colorblind_mode: boolean
  }
  risk: {
    breakeven_threshold_r: number
    breakeven_handling: 'excluded' | 'loss' | 'win'
    breakeven_threshold_money: number
    fallback_risk_mode: 'from_stop' | 'fixed_amount' | 'percent_of_balance' | 'none'
    fixed_risk_amount: number
    risk_percent: number
    account_size: number
    include_commission_in_pnl: boolean
    include_swap_in_pnl: boolean
    r_uses_net_pnl: boolean
  }
  stats: {
    risk_free_rate: number
    trading_days_per_year: number
    sharpe_basis: 'daily' | 'trade'
    min_trades_for_score: number
  }
  zulu_score: {
    weights: Record<string, number>
    targets: Record<string, number>
  }
  mt5: {
    sync_mode: 'ea' | 'bridge' | 'off'
    bridge_url: string
    bridge_timeout_seconds: number
    auto_sync_on_load: boolean
    auto_sync_min_interval_seconds: number
    history_days_on_full_sync: number
  }
  charts: {
    provider: 'local' | 'tradingview'
    default_timeframe: string
    candles_before: number
    candles_after: number
    tradingview_prefix: string
    symbol_map: Record<string, string>
  }
}

export interface SyncStatus {
  account_id: number | null
  login: string | null
  name: string | null
  balance: number | null
  equity: number | null
  currency: string | null
  last_sync_at: string | null
  last_sync_source: string | null
  total_deals: number
  total_trades: number
  open_trades: number
  sync_mode: string
  bridge_reachable: boolean | null
  bridge_connected: boolean | null
  credentials_configured: boolean
  message: string
}

export interface MT5Credentials {
  configured: boolean
  server: string
  login: string
  /** False when TZ_SECRET_KEY changed since the password was saved. */
  password_readable: boolean
}

export interface MT5ConnectResult {
  ok: boolean
  account?: {
    login: string
    name: string
    server: string
    company: string
    currency: string
    leverage: number
    balance: number
    equity: number
    trade_allowed: boolean
  }
  account_id?: number
}

export interface Account {
  id: number
  login: string
  name: string
  broker: string
  server: string
  currency: string
  leverage: number
  balance: number
  equity: number
  initial_balance: number
  is_default: boolean
  last_sync_at: string | null
  last_sync_source: string
}

export interface Candle {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface CandleResponse {
  symbol: string
  timeframe: string
  candles: Candle[]
  source: string
}

export interface User {
  id: number
  username: string
  last_login_at: string | null
}

export interface SystemInfo {
  version: string
  data_dir: string
  ingest_token_configured: boolean
  secret_key_ephemeral: boolean
  trades: number
  accounts: number
}

export interface SyncLogEntry {
  id: number
  account_id: number | null
  source: string
  status: string
  deals_received: number
  deals_new: number
  trades_upserted: number
  message: string
  created_at: string
}
