import { format, formatDistanceStrict, parseISO } from 'date-fns'

export function money(
  value: number | null | undefined,
  symbol = '$',
  options: { decimals?: number; sign?: boolean; compact?: boolean } = {},
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const { decimals = 2, sign = false, compact = false } = options
  const abs = Math.abs(value)

  let body: string
  if (compact && abs >= 10_000) {
    body = `${(abs / 1000).toLocaleString(undefined, { maximumFractionDigits: 1 })}k`
  } else {
    body = abs.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })
  }

  const prefix = value < 0 ? '-' : sign && value > 0 ? '+' : ''
  return `${prefix}${symbol}${body}`
}

export function num(
  value: number | null | undefined,
  decimals = 2,
  options: { sign?: boolean } = {},
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const text = value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
  return options.sign && value > 0 ? `+${text}` : text
}

/** A money figure, or what it was worth to the account that took it.
 *
 * The whole journal can be read without saying what any account is worth:
 * every currency figure has a share of something behind it, and with amounts
 * hidden that share is what gets printed. Costs go through here too --
 * commission and swap are real money leaving the account, so they belong in
 * the result rather than being dropped from it, and a percentage says what
 * they cost without saying what they cost *of*.
 *
 * A figure with no base is the one case that cannot be answered: nothing is
 * known to divide by, and falling back to the amount would put the number on
 * screen that all of this exists to keep off it.
 */
export function amount(
  value: number | null | undefined,
  base: number | null | undefined,
  currency: string,
  options: { showAmounts: boolean; sign?: boolean; decimals?: number } = {
    showAmounts: true,
  },
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  if (options.showAmounts) {
    return money(value, currency, { sign: options.sign, decimals: options.decimals })
  }
  if (!base || base <= 0) return '—'
  const share = (value / base) * 100
  return `${options.sign && share > 0 ? '+' : ''}${num(share, 2)}%`
}

export function percent(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(decimals)}%`
}

export function rMultiple(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value > 0 ? '+' : ''}${value.toFixed(decimals)}R`
}

/** Profit factor is capped server-side; render the cap as infinity. */
export function profitFactor(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  if (value >= 999) return '∞'
  return value.toFixed(2)
}

export function price(value: number | null | undefined, digits = 5): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}

export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  if (seconds < 86400) {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.round((seconds % 3600) / 60)
    return minutes ? `${hours}h ${minutes}m` : `${hours}h`
  }
  const days = Math.floor(seconds / 86400)
  const hours = Math.round((seconds % 86400) / 3600)
  return hours ? `${days}d ${hours}h` : `${days}d`
}

/** Whether times are written 13:05 or 1:05 PM.
 *
 *  Module state rather than an argument on seventeen call sites: every time in
 *  the journal already goes through the helpers below, so setting it in one
 *  place makes all of them right -- including the ones nobody remembers.
 *  SettingsProvider keeps it in step, and its own re-render is what redraws
 *  the times when it changes.
 */
let clock: '12h' | '24h' = '24h'

export function setClock(next: '12h' | '24h') {
  clock = next
}

/** For the places that format a time themselves, because they need a timezone
 *  the date-fns helpers here do not take. */
export function hour12(): boolean {
  return clock === '12h'
}

const TIME_PATTERN = () => (clock === '12h' ? 'h:mm a' : 'HH:mm')

/**
 * Whose clock the journal is written in.
 *
 * MetaTrader stamps everything with the broker's server clock and says nothing
 * about it, so a timestamp from a trade arrives as bare digits -- and bare
 * digits are what a browser reads as its own local time, which is how they
 * have always been rendered here: exactly as the terminal shows them.
 *
 * Reading them as the day was actually lived instead needs two things the
 * digits do not carry: how far the broker's clock runs from UTC, and which
 * timezone to write the result in. Both arrive here from SettingsProvider.
 *
 * Kept per account rather than as one number, because two brokers are not
 * necessarily on the same clock and a journal covering both would otherwise
 * put one of them an hour out. An account nobody has reported an offset for
 * stays on the broker's clock rather than being guessed at.
 *
 * Timestamps that arrive *with* an offset are ours, not the broker's -- when a
 * terminal last reported, when a copy was placed -- and are already unambiguous
 * moments. Those are never touched.
 */
type Clock = {
  mode: 'broker' | 'local'
  zone: string
  offsets: Map<number, number>
  /** For anything not tied to one account -- the default account's. */
  fallback: number | null
}

let clockSetting: Clock = { mode: 'broker', zone: 'UTC', offsets: new Map(), fallback: null }

export function setTimeDisplay(next: Clock) {
  clockSetting = next
}

const MARKED = /Z$|[+-]\d\d:?\d\d$/
const HAS_TIME = /\d{2}:\d{2}/

/** Formatters are not cheap to build and this runs per row. */
const zoneFormatters = new Map<string, Intl.DateTimeFormat>()

function zoneFormatter(zone: string): Intl.DateTimeFormat {
  let found = zoneFormatters.get(zone)
  if (!found) {
    found = new Intl.DateTimeFormat('en-GB', {
      timeZone: zone,
      hourCycle: 'h23',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
    zoneFormatters.set(zone, found)
  }
  return found
}

/**
 * A broker timestamp as the wall clock of ``zone``.
 *
 * Returned as a Date whose *local* components are the wanted ones, because
 * that is what date-fns prints. Built from the parts rather than by adding an
 * offset in milliseconds: the arithmetic version silently gains or loses an
 * hour for a timestamp that lands near a daylight-saving change.
 */
function asZoned(value: string, offsetMinutes: number, zone: string): Date {
  const instant = new Date(Date.parse(`${value}Z`) - offsetMinutes * 60_000)
  const parts: Record<string, number> = {}
  for (const part of zoneFormatter(zone).formatToParts(instant)) {
    if (part.type !== 'literal') parts[part.type] = Number(part.value)
  }
  return new Date(
    parts.year,
    parts.month - 1,
    parts.day,
    parts.hour,
    parts.minute,
    parts.second,
  )
}

export function toDate(
  value: string | Date | null | undefined,
  account?: number | null,
): Date | null {
  if (!value) return null
  if (value instanceof Date) return value
  if (clockSetting.mode === 'broker' || MARKED.test(value)) return parseISO(value)
  // A bare date is a calendar day, not a moment: the day a trade was filed
  // under, the ends of the period in view. Converting one moves it to the day
  // before whenever the broker is ahead of the zone, which is how "7 Jul – 5
  // Aug" became "6 Jul – 4 Aug" merely because the clock was switched.
  if (!HAS_TIME.test(value)) return parseISO(value)

  const offset =
    (account === null || account === undefined ? undefined : clockSetting.offsets.get(account)) ??
    clockSetting.fallback
  if (offset === null || offset === undefined) return parseISO(value)
  return asZoned(value, offset, clockSetting.zone)
}

export function dateTime(
  value: string | null | undefined,
  pattern?: string,
  account?: number | null,
): string {
  const date = toDate(value, account)
  if (!date) return '—'
  return format(date, pattern ?? `dd MMM yyyy ${TIME_PATTERN()}`)
}

export function dateOnly(
  value: string | null | undefined,
  pattern = 'dd MMM yyyy',
  account?: number | null,
): string {
  const date = toDate(value, account)
  return date ? format(date, pattern) : '—'
}

export function timeOnly(value: string | null | undefined, account?: number | null): string {
  const date = toDate(value, account)
  return date ? format(date, TIME_PATTERN()) : '—'
}

export function relative(value: string | null | undefined): string {
  const date = toDate(value)
  if (!date) return 'never'
  return `${formatDistanceStrict(date, new Date())} ago`
}

export function isoDate(date: Date): string {
  return format(date, 'yyyy-MM-dd')
}

/** Text colour for a signed value. Always paired with a visible +/- sign so
 *  the colour is reinforcement, never the only signal. */
export function pnlClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return 'text-[var(--tz-text-muted)]'
  return value > 0 ? 'text-[var(--tz-gain-text)]' : 'text-[var(--tz-loss-text)]'
}

/**
 * Colour for a trade's result, by outcome rather than by sign.
 *
 * A breakeven rarely lands on exactly zero -- commission alone puts it a few
 * pence either side -- so colouring by sign paints it red or green and hides
 * the one fact that matters about it: it was neither. Breakevens get their own
 * colour, and the sign is only consulted for genuine wins and losses.
 */
export function outcomeClass(
  outcome: string | null | undefined,
  value: number | null | undefined,
): string {
  if (outcome === 'breakeven') return 'text-[var(--tz-breakeven-text)]'
  return pnlClass(value)
}

/** Mark colour (bars, dots) for a trade's result. */
export function outcomeColor(
  outcome: string | null | undefined,
  value: number | null | undefined,
): string {
  if (outcome === 'breakeven') return 'var(--tz-breakeven)'
  return pnlColor(value)
}

/** Mark colour (bars, areas, dots) for a signed value. */
export function pnlColor(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return 'var(--tz-flat)'
  return value > 0 ? 'var(--tz-gain)' : 'var(--tz-loss)'
}

export function outcomeLabel(outcome: string): string {
  switch (outcome) {
    case 'win':
      return 'Win'
    case 'loss':
      return 'Loss'
    case 'breakeven':
      return 'Breakeven'
    default:
      return 'Open'
  }
}

/** Readable contrast colour for a user-picked tag colour. */
export function contrastText(hex: string): string {
  const clean = hex.replace('#', '')
  if (clean.length !== 6) return '#ffffff'
  const r = parseInt(clean.slice(0, 2), 16)
  const g = parseInt(clean.slice(2, 4), 16)
  const b = parseInt(clean.slice(4, 6), 16)
  const luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
  return luminance > 0.6 ? '#101320' : '#ffffff'
}
