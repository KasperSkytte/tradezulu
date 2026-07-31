import clsx from 'clsx'
import type { ReactNode } from 'react'
import { define } from '../lib/glossary'
import { Hint } from './ui'

export function StatTile({
  label,
  value,
  hint,
  sub,
  accent,
  visual,
  className,
}: {
  label: string
  value: ReactNode
  hint?: string
  sub?: ReactNode
  /** Colour applied to the value; use for signed money only. */
  accent?: string
  visual?: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('tz-card flex items-center gap-2.5 p-3.5 sm:p-4', className)}>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <p className="text-xs font-medium leading-tight text-[var(--tz-text-muted)]">{label}</p>
          {/* An explicit hint wins; otherwise the glossary answers for the
              label, so a term is never left unexplained just because nobody
              remembered to write one at this call site. */}
          {(hint ?? define(label)) && <Hint text={hint ?? define(label)!} />}
        </div>
        <p
          className="tabular mt-1 text-xl font-semibold tracking-tight 2xl:text-2xl"
          style={accent ? { color: accent } : undefined}
        >
          {value}
        </p>
        {sub && <div className="mt-0.5 text-xs text-[var(--tz-text-muted)]">{sub}</div>}
      </div>
      {visual && <div className="shrink-0">{visual}</div>}
    </div>
  )
}

/** Half-donut gauge used for the win-rate tiles. */
export function Gauge({
  value,
  size = 54,
  color = 'var(--tz-gain)',
  track = 'var(--tz-loss)',
}: {
  value: number | null
  size?: number
  color?: string
  track?: string
}) {
  const radius = size / 2 - 5
  const circumference = Math.PI * radius
  const filled = value === null ? 0 : Math.max(0, Math.min(100, value)) / 100

  return (
    <svg width={size} height={size / 2 + 6} viewBox={`0 0 ${size} ${size / 2 + 6}`}>
      <path
        d={`M 5 ${size / 2} A ${radius} ${radius} 0 0 1 ${size - 5} ${size / 2}`}
        fill="none"
        stroke={track}
        strokeWidth={5}
        strokeLinecap="round"
        opacity={0.55}
      />
      <path
        d={`M 5 ${size / 2} A ${radius} ${radius} 0 0 1 ${size - 5} ${size / 2}`}
        fill="none"
        stroke={color}
        strokeWidth={5}
        strokeLinecap="round"
        strokeDasharray={`${circumference * filled} ${circumference}`}
      />
    </svg>
  )
}

/** Two-sided bar comparing average win against average loss. */
export function WinLossBar({
  win,
  loss,
  formatValue,
}: {
  win: number | null
  loss: number | null
  formatValue: (value: number | null) => string
}) {
  const winValue = Math.abs(win ?? 0)
  const lossValue = Math.abs(loss ?? 0)
  const total = winValue + lossValue
  const winShare = total > 0 ? (winValue / total) * 100 : 50

  return (
    <div className="w-20">
      <div className="flex h-2 gap-[2px] overflow-hidden rounded-full">
        <div style={{ width: `${winShare}%`, backgroundColor: 'var(--tz-gain)' }} />
        <div style={{ width: `${100 - winShare}%`, backgroundColor: 'var(--tz-loss)' }} />
      </div>
      <div className="tabular mt-1 flex justify-between text-[0.65rem]">
        <span className="text-[var(--tz-gain-text)]">{formatValue(win)}</span>
        <span className="text-[var(--tz-loss-text)]">{formatValue(loss)}</span>
      </div>
    </div>
  )
}

/** Compact sparkline for a tile; no axes, no labels — the tile carries those. */
export function Sparkline({
  values,
  width = 64,
  height = 28,
}: {
  values: number[]
  width?: number
  height?: number
}) {
  if (values.length < 2) return null
  const min = Math.min(...values, 0)
  const max = Math.max(...values, 0)
  const span = max - min || 1
  const step = width / (values.length - 1)
  const points = values
    .map((value, index) => `${index * step},${height - ((value - min) / span) * height}`)
    .join(' ')
  const positive = (values.at(-1) ?? 0) >= 0
  const zeroY = height - ((0 - min) / span) * height

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden>
      <line
        x1="0"
        x2={width}
        y1={zeroY}
        y2={zeroY}
        stroke="var(--tz-border-strong)"
        strokeWidth="1"
      />
      <polyline
        points={points}
        fill="none"
        stroke={positive ? 'var(--tz-gain)' : 'var(--tz-loss)'}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  )
}
