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

export function toDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null
  return value instanceof Date ? value : parseISO(value)
}

export function dateTime(value: string | null | undefined, pattern?: string): string {
  const date = toDate(value)
  if (!date) return '—'
  return format(date, pattern ?? `dd MMM yyyy ${TIME_PATTERN()}`)
}

export function dateOnly(value: string | null | undefined, pattern = 'dd MMM yyyy'): string {
  const date = toDate(value)
  return date ? format(date, pattern) : '—'
}

export function timeOnly(value: string | null | undefined): string {
  const date = toDate(value)
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
