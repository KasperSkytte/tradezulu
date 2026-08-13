/**
 * Shared chart building blocks.
 *
 * Conventions applied throughout, so every chart in the app reads the same:
 *  - one measure per chart, one axis, never a second y-scale;
 *  - profit/loss is encoded by position around a zero baseline first and by
 *    colour second, and every figure carries its sign;
 *  - gridlines are hairline and recessive, axis text uses text tokens rather
 *    than the series colour;
 *  - every chart has a hover tooltip.
 */

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ReactNode } from 'react'
import { dateOnly, money, num, percent } from '../lib/format'

const AXIS = {
  stroke: 'var(--tz-text-faint)',
  fontSize: 11,
  tickLine: false,
  axisLine: false,
} as const

const GRID = {
  stroke: 'var(--tz-grid)',
  strokeDasharray: '0',
  vertical: false,
} as const

export function ChartTooltip({
  title,
  rows,
}: {
  title: ReactNode
  rows: { label: string; value: ReactNode; color?: string }[]
}) {
  return (
    <div className="tz-card px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 font-medium">{title}</p>
      <div className="space-y-0.5">
        {rows.map((row) => (
          <div key={row.label} className="flex items-center gap-3">
            {row.color && (
              <span
                className="size-2 shrink-0 rounded-full"
                style={{ backgroundColor: row.color }}
              />
            )}
            <span className="text-[var(--tz-text-muted)]">{row.label}</span>
            <span className="tabular ml-auto font-medium">{row.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function compactMoney(value: number, symbol: string) {
  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  if (abs >= 1_000_000) return `${sign}${symbol}${(abs / 1_000_000).toFixed(1)}M`
  if (abs >= 1_000) return `${sign}${symbol}${(abs / 1_000).toFixed(abs >= 10_000 ? 0 : 1)}k`
  return `${sign}${symbol}${abs.toFixed(0)}`
}

/* --------------------------------------------------------------------- */

export interface CumulativePoint {
  label: string
  value: number
  extra?: string
  /** Optional second series: equity, when the account has samples. */
  equity?: number
  /** Money paid in or taken out on this day, if any. Marked rather than
   *  plotted: it moves the equity line without being performance, and a step
   *  with no explanation is the kind of thing people spend an evening on. */
  flow?: number
}

export function CumulativeChart({
  data,
  currency,
  height = 220,
  valueLabel = 'Cumulative P&L',
  formatValue,
  formatAxis,
}: {
  data: CumulativePoint[]
  currency: string
  height?: number
  valueLabel?: string
  formatValue?: (value: number) => string
  formatAxis?: (value: number) => string
}) {
  const format = formatValue ?? ((value: number) => money(value, currency, { sign: true }))
  const last = data.at(-1)?.value ?? 0
  const positive = last >= 0

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -12 }}>
        <defs>
          <linearGradient id="tz-cum-fill" x1="0" y1="0" x2="0" y2="1">
            <stop
              offset="0%"
              stopColor={positive ? 'var(--tz-gain)' : 'var(--tz-loss)'}
              stopOpacity={0.28}
            />
            <stop
              offset="100%"
              stopColor={positive ? 'var(--tz-gain)' : 'var(--tz-loss)'}
              stopOpacity={0}
            />
          </linearGradient>
        </defs>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="label" {...AXIS} minTickGap={28} />
        <YAxis
          {...AXIS}
          width={62}
          // Same units as the tooltip: with amounts hidden, a
          // currency axis would give the scale away regardless.
          tickFormatter={(value) =>
            formatAxis ? formatAxis(Number(value)) : compactMoney(value, currency)
          }
        />
        <ReferenceLine y={0} stroke="var(--tz-border-strong)" />
        {/* A tick under every day money went in or out. The equity line steps
            at these, and without a mark the step looks like a trading result
            -- which is the one thing it is not. */}
        {data
          .filter((point) => point.flow)
          .map((point) => (
            <ReferenceLine
              key={`flow-${point.label}`}
              x={point.label}
              stroke="var(--tz-text-faint)"
              strokeDasharray="2 3"
              strokeWidth={1}
              label={{
                value: (point.flow ?? 0) > 0 ? '▲' : '▼',
                position: 'insideBottom',
                fill: 'var(--tz-text-faint)',
                fontSize: 9,
              }}
            />
          ))}
        <Tooltip
          cursor={{ stroke: 'var(--tz-border-strong)', strokeWidth: 1 }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <ChartTooltip
                title={String(label)}
                rows={[
                  {
                    label: valueLabel,
                    value: format(Number(payload[0].value)),
                    color: positive ? 'var(--tz-gain)' : 'var(--tz-loss)',
                  },
                  ...(payload[0].payload?.equity != null
                    ? [
                        {
                          label: 'Equity',
                          value: format(Number(payload[0].payload.equity)),
                          color: 'var(--tz-entry)',
                        },
                        {
                          // The gap between the lines is the point: what was
                          // on the table and had not been taken.
                          label: 'Unrealised',
                          value: format(
                            Number(payload[0].payload.equity) - Number(payload[0].value),
                          ),
                        },
                      ]
                    : []),
                  ...(payload[0].payload?.flow
                    ? [
                        {
                          label: Number(payload[0].payload.flow) > 0 ? 'Paid in' : 'Taken out',
                          value: format(Number(payload[0].payload.flow)),
                          color: 'var(--tz-text-faint)',
                        },
                      ]
                    : []),
                  ...(payload[0].payload?.extra
                    ? [{ label: 'Detail', value: String(payload[0].payload.extra) }]
                    : []),
                ]}
              />
            ) : null
          }
        />
        <Area
          type="monotone"
          dataKey="value"
          stroke={positive ? 'var(--tz-gain)' : 'var(--tz-loss)'}
          strokeWidth={2}
          fill="url(#tz-cum-fill)"
          activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--tz-surface)' }}
          isAnimationActive={false}
        />
        {/* Equity, when there is any. Balance only moves when something
            closes, so on its own it cannot show a position running up and
            being handed back. Drawn thin and unfilled so it reads as a
            companion to the realised line rather than competing with it. */}
        {data.some((point) => point.equity != null) && (
          <Area
            type="monotone"
            dataKey="equity"
            stroke="var(--tz-entry)"
            strokeWidth={1.5}
            strokeDasharray="4 3"
            fill="none"
            connectNulls
            activeDot={{ r: 3, strokeWidth: 2, stroke: 'var(--tz-surface)' }}
            isAnimationActive={false}
          />
        )}
      </AreaChart>
    </ResponsiveContainer>
  )
}

/* --------------------------------------------------------------------- */

export interface SignedBar {
  label: string
  value: number
  meta?: string
}

export function SignedBarChart({
  data,
  currency,
  height = 220,
  layout = 'vertical',
  valueLabel = 'Net P&L',
  formatValue,
  formatAxis,
  onSelect,
}: {
  data: SignedBar[]
  currency: string
  height?: number
  formatAxis?: (value: number) => string
  /** 'vertical' means vertical bars (columns); 'horizontal' means rows. */
  layout?: 'vertical' | 'horizontal'
  valueLabel?: string
  formatValue?: (value: number) => string
  onSelect?: (item: SignedBar) => void
}) {
  const format = formatValue ?? ((value: number) => money(value, currency, { sign: true }))
  const isRows = layout === 'horizontal'

  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart
        data={data}
        layout={isRows ? 'vertical' : 'horizontal'}
        margin={
          isRows
            ? { top: 4, right: 16, bottom: 4, left: 4 }
            : { top: 6, right: 8, bottom: 0, left: -12 }
        }
        barCategoryGap={isRows ? '18%' : '22%'}
      >
        <CartesianGrid {...GRID} vertical={isRows} horizontal={!isRows} />
        {isRows ? (
          <>
            <XAxis
              type="number"
              {...AXIS}
              tickFormatter={(v) =>
                formatAxis ? formatAxis(Number(v)) : compactMoney(v, currency)
              }
            />
            <YAxis type="category" dataKey="label" {...AXIS} width={92} />
          </>
        ) : (
          <>
            <XAxis dataKey="label" {...AXIS} minTickGap={16} />
            <YAxis
              {...AXIS}
              width={62}
              tickFormatter={(v) =>
                formatAxis ? formatAxis(Number(v)) : compactMoney(v, currency)
              }
            />
          </>
        )}
        <ReferenceLine {...(isRows ? { x: 0 } : { y: 0 })} stroke="var(--tz-border-strong)" />
        <Tooltip
          cursor={{ fill: 'var(--tz-surface-hover)', opacity: 0.5 }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <ChartTooltip
                title={String(label)}
                rows={[
                  {
                    label: valueLabel,
                    value: format(Number(payload[0].value)),
                    color:
                      Number(payload[0].value) >= 0 ? 'var(--tz-gain)' : 'var(--tz-loss)',
                  },
                  ...(payload[0].payload?.meta
                    ? [{ label: 'Detail', value: String(payload[0].payload.meta) }]
                    : []),
                ]}
              />
            ) : null
          }
        />
        <Bar
          dataKey="value"
          radius={isRows ? [0, 4, 4, 0] : [4, 4, 0, 0]}
          maxBarSize={24}
          isAnimationActive={false}
          onClick={(item) => onSelect?.(item.payload as SignedBar)}
          cursor={onSelect ? 'pointer' : undefined}
        >
          {data.map((item) => (
            <Cell
              key={item.label}
              fill={item.value >= 0 ? 'var(--tz-gain)' : 'var(--tz-loss)'}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/* --------------------------------------------------------------------- */

export function ScoreRadar({
  data,
  height = 240,
}: {
  data: { axis: string; value: number; target: number }[]
  height?: number
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RadarChart data={data} outerRadius="72%">
        <PolarGrid stroke="var(--tz-grid)" />
        <PolarAngleAxis
          dataKey="axis"
          tick={{ fill: 'var(--tz-text-muted)', fontSize: 11 }}
        />
        <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
        <Tooltip
          content={({ active, payload }) =>
            active && payload?.length ? (
              <ChartTooltip
                title={String(payload[0].payload.axis)}
                rows={[
                  {
                    label: 'Score',
                    value: `${num(Number(payload[0].payload.value), 0)} / 100`,
                    color: 'var(--color-zulu-400)',
                  },
                ]}
              />
            ) : null
          }
        />
        <Radar
          name="Score"
          dataKey="value"
          stroke="var(--color-zulu-400)"
          strokeWidth={2}
          fill="var(--color-zulu-500)"
          fillOpacity={0.22}
          isAnimationActive={false}
        />
      </RadarChart>
    </ResponsiveContainer>
  )
}

/* --------------------------------------------------------------------- */

export function WinRateLine({
  data,
  height = 200,
}: {
  data: { label: string; winRate: number | null }[]
  height?: number
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="label" {...AXIS} minTickGap={28} />
        <YAxis
          {...AXIS}
          width={46}
          domain={[0, 100]}
          ticks={[0, 25, 50, 75, 100]}
          tickFormatter={(v) => `${v}%`}
        />
        <ReferenceLine y={50} stroke="var(--tz-border-strong)" strokeDasharray="4 4" />
        <Tooltip
          cursor={{ stroke: 'var(--tz-border-strong)', strokeWidth: 1 }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <ChartTooltip
                title={String(label)}
                rows={[
                  {
                    label: 'Rolling win rate',
                    value: percent(Number(payload[0].value)),
                    color: 'var(--color-zulu-400)',
                  },
                ]}
              />
            ) : null
          }
        />
        <Line
          type="monotone"
          dataKey="winRate"
          stroke="var(--color-zulu-400)"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, strokeWidth: 2, stroke: 'var(--tz-surface)' }}
          connectNulls
          isAnimationActive={false}
        />
      </LineChart>
    </ResponsiveContainer>
  )
}

/* --------------------------------------------------------------------- */

export function DrawdownChart({
  data,
  currency,
  height = 180,
  /** How to write a drawdown. Given when the page is hiding money amounts. */
  format,
}: {
  data: { label: string; drawdown: number }[]
  currency: string
  height?: number
  format?: (value: number) => string
}) {
  const write = format ?? ((value: number) => money(value, currency))
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -12 }}>
        <defs>
          <linearGradient id="tz-dd-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--tz-loss)" stopOpacity={0.05} />
            <stop offset="100%" stopColor="var(--tz-loss)" stopOpacity={0.3} />
          </linearGradient>
        </defs>
        <CartesianGrid {...GRID} />
        <XAxis dataKey="label" {...AXIS} minTickGap={28} />
        <YAxis
          {...AXIS}
          width={62}
          tickFormatter={(value) =>
            format ? format(-Math.abs(value)) : compactMoney(-Math.abs(value), currency)
          }
        />
        <Tooltip
          cursor={{ stroke: 'var(--tz-border-strong)', strokeWidth: 1 }}
          content={({ active, payload, label }) =>
            active && payload?.length ? (
              <ChartTooltip
                title={String(label)}
                rows={[
                  {
                    label: 'Drawdown from peak',
                    value: write(-Math.abs(Number(payload[0].value))),
                    color: 'var(--tz-loss)',
                  },
                ]}
              />
            ) : null
          }
        />
        <Area
          type="monotone"
          dataKey="drawdown"
          stroke="var(--tz-loss)"
          strokeWidth={1.5}
          fill="url(#tz-dd-fill)"
          isAnimationActive={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  )
}

/* --------------------------------------------------------------------- */

/** A win/loss/breakeven split shown as one stacked bar with a real legend. */
export function OutcomeSplit({
  wins,
  losses,
  breakevens,
}: {
  wins: number
  losses: number
  breakevens: number
}) {
  const total = wins + losses + breakevens
  if (!total) return <p className="text-sm text-[var(--tz-text-muted)]">No trades yet</p>

  const segments = [
    { label: 'Wins', value: wins, color: 'var(--tz-gain)' },
    { label: 'Breakeven', value: breakevens, color: 'var(--tz-flat)' },
    { label: 'Losses', value: losses, color: 'var(--tz-loss)' },
  ].filter((segment) => segment.value > 0)

  return (
    <div>
      <div className="flex h-2.5 w-full gap-[2px] overflow-hidden rounded-full">
        {segments.map((segment) => (
          <div
            key={segment.label}
            title={`${segment.label}: ${segment.value}`}
            style={{
              width: `${(segment.value / total) * 100}%`,
              backgroundColor: segment.color,
            }}
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
        {segments.map((segment) => (
          <span
            key={segment.label}
            className="flex items-center gap-1.5 text-xs text-[var(--tz-text-muted)]"
          >
            <span
              className="size-2 rounded-full"
              style={{ backgroundColor: segment.color }}
            />
            {segment.label}
            <span className="tabular font-medium text-[var(--tz-text)]">{segment.value}</span>
          </span>
        ))}
      </div>
    </div>
  )
}

export { AXIS, GRID, Legend, dateOnly }
