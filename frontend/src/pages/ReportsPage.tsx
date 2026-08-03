import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { BarChart3 } from 'lucide-react'
import clsx from 'clsx'
import { api } from '../lib/api'
import { useFilters } from '../lib/filters'
import { useSettings } from '../lib/settings'
import { dateOnly, money, num, percent, pnlClass, profitFactor } from '../lib/format'
import type { BreakdownRow, Breakdowns, Summary } from '../lib/types'
import { FilterBar } from '../components/FilterBar'
import { DrawdownChart, SignedBarChart, WinRateLine } from '../components/charts'
import { Card, CardHeader, EmptyState, ErrorState, SegmentedControl, Skeleton } from '../components/ui'

// Three ways to read the same row. Money answers "what did it pay", R answers
// "was the risk worth taking", and percent answers "how much of the account did
// it move" -- which are different questions, and people do not all ask the same
// one.
type Metric = 'net_pnl' | 'total_r' | 'percent'

// Every key of Breakdowns except the account size, which is a number rather
// than a set of rows.
type BreakdownKey = Exclude<keyof Breakdowns, 'account_size'>

const SECTIONS: { key: BreakdownKey; title: string; hint: string }[] = [
  { key: 'by_symbol', title: 'By symbol', hint: 'Which instruments actually pay you.' },
  {
    key: 'by_tag',
    title: 'By tag',
    hint: 'The most valuable view in the journal: what your mistakes cost, in money.',
  },
  { key: 'by_setup', title: 'By setup', hint: 'Performance of each named plan.' },
  { key: 'by_weekday', title: 'By day of week', hint: 'Are Mondays quietly bleeding you out?' },
  { key: 'by_hour', title: 'By hour opened', hint: 'Session and time-of-day edge.' },
  { key: 'by_duration', title: 'By hold time', hint: 'Do you cut winners or sit on losers?' },
  {
    key: 'by_r_multiple',
    title: 'By R multiple',
    hint: 'The shape of your distribution. A healthy one has a long right tail.',
  },
  { key: 'by_direction', title: 'Long vs short', hint: 'Directional bias in your results.' },
]

export function ReportsPage() {
  const { params } = useFilters()
  const { currency, showAmounts } = useSettings()
  const [metric, setMetric] = useState<Metric>('net_pnl')

  const summaryQuery = useQuery({
    queryKey: ['stats', 'summary', params],
    queryFn: () => api.get<Summary>('/stats/summary', params),
  })

  const breakdownQuery = useQuery({
    queryKey: ['stats', 'breakdowns', params],
    queryFn: () => api.get<Breakdowns>('/stats/breakdowns', params),
  })

  const rollingQuery = useQuery({
    queryKey: ['stats', 'rolling', params],
    queryFn: () =>
      api.get<{ date: string; win_rate: number | null; net_pnl: number }[]>('/stats/rolling', {
        ...params,
        window: 20,
      }),
  })

  if (summaryQuery.isError || breakdownQuery.isError) {
    return (
      <ErrorState
        error={summaryQuery.error ?? breakdownQuery.error}
        retry={() => {
          void summaryQuery.refetch()
          void breakdownQuery.refetch()
        }}
      />
    )
  }

  const summary = summaryQuery.data
  const breakdowns = breakdownQuery.data

  // Percent is derived from money rather than carried separately: a share of
  // what the account was worth when the period opened is exactly what this is.
  // The account size is the fallback for a journal with no recorded balance.
  const accountSize = summary?.opening_balance || breakdowns?.account_size || 0

  // The same rule as the dashboard, and for the same reason: with amounts
  // switched off this page can be screenshotted and shared without showing
  // what the account is worth. Every figure here becomes a share of it --
  // charts, axes, tooltips and tables alike, or the ones left in money would
  // give the size away on their own.
  const hideMoney = !showAmounts && accountSize > 0
  const cash = (value: number | null | undefined, options?: { sign?: boolean; decimals?: number }) => {
    if (value == null) return '—'
    if (!hideMoney) return money(value, currency, options)
    const pct = (value / accountSize) * 100
    return `${pct > 0 ? '+' : ''}${num(pct, 2)}%`
  }

  const formatMetric = (value: number) => {
    if (metric === 'total_r') return `${num(value, 2)}R`
    if (metric === 'percent') {
      return accountSize > 0 ? `${value > 0 ? '+' : ''}${num(value, 2)}%` : '—'
    }
    return cash(value, { sign: true })
  }

  // Gridlines give the scale away on their own, so the axis has to speak the
  // same units as the bars above it. Unsigned and coarser than the values:
  // this is a ruler, not a reading.
  const formatAxis = (value: number) => {
    if (metric === 'total_r') return `${num(value, 1)}R`
    if (hideMoney) return `${num((value / accountSize) * 100, 1)}%`
    return money(value, currency, { decimals: 0, compact: true })
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <FilterBar />
        <div className="ml-auto">
          <SegmentedControl
            size="sm"
            value={metric}
            onChange={setMetric}
            options={[
              // Named after what it actually shows, which depends on whether
              // money is being hidden.
              { value: 'net_pnl', label: hideMoney ? 'Percent' : 'Money' },
              { value: 'total_r', label: 'R multiple' },
            ]}
          />
        </div>
      </div>

      {summaryQuery.isLoading || !summary ? (
        <Skeleton className="h-64" />
      ) : summary.counts.total === 0 ? (
        <Card>
          <EmptyState
            icon={<BarChart3 size={36} strokeWidth={1.4} />}
            title="Nothing to report yet"
            description="No trades closed in this period."
          />
        </Card>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader
                title="Rolling win rate (20 days)"
                hint="Smooths out single sessions so a trend is visible."
              />
              {rollingQuery.data?.length ? (
                <WinRateLine
                  data={rollingQuery.data.map((point) => ({
                    label: dateOnly(point.date, 'd MMM'),
                    winRate: point.win_rate,
                  }))}
                />
              ) : (
                <Skeleton className="h-[200px]" />
              )}
            </Card>

            <Card>
              <CardHeader
                title="Drawdown"
                hint="How far below the equity high-water mark you were at each closed trade."
              />
              <DrawdownChart
                data={summary.equity_curve.map((point) => ({
                  label: dateOnly(point.time, 'd MMM'),
                  drawdown: point.drawdown,
                }))}
                currency={currency}
                format={hideMoney ? (value) => `${num((value / accountSize) * 100, 1)}%` : undefined}
              />
            </Card>
          </div>

          {breakdownQuery.isLoading || !breakdowns ? (
            <Skeleton className="h-96" />
          ) : (
            <div className="grid items-start gap-4 lg:grid-cols-2">
              {SECTIONS.map((section) => (
                <BreakdownCard
                  key={section.key}
                  title={section.title}
                  hint={section.hint}
                  rows={breakdowns[section.key]}
                  metric={metric}
                  currency={currency}
                  accountSize={accountSize}
                  hideMoney={hideMoney}
                  formatMetric={formatMetric}
                  formatAxis={formatAxis}
                  cash={cash}
                />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function BreakdownCard({
  title,
  hint,
  rows,
  metric,
  currency,
  accountSize,
  hideMoney,
  formatMetric,
  formatAxis,
  cash,
}: {
  title: string
  hint: string
  rows: BreakdownRow[]
  metric: Metric
  currency: string
  accountSize: number
  hideMoney: boolean
  formatMetric: (value: number) => string
  formatAxis: (value: number) => string
  cash: (value: number | null | undefined, options?: { sign?: boolean; decimals?: number }) => string
}) {
  const [view, setView] = useState<'chart' | 'table'>('chart')

  if (!rows.length) {
    return (
      <Card>
        <CardHeader title={title} hint={hint} />
        <p className="py-6 text-center text-sm text-[var(--tz-text-muted)]">No data</p>
      </Card>
    )
  }

  const data = rows
    .map((row) => ({
      label: row.key,
      value:
        metric === 'total_r'
          ? (row.total_r ?? 0)
          : metric === 'percent'
            ? accountSize > 0
              ? ((row.net_pnl ?? 0) / accountSize) * 100
              : 0
            : (row.net_pnl ?? 0),
      meta: `${row.trades} trades · ${percent(row.win_rate)} win rate`,
    }))
    .slice(0, 12)

  return (
    <Card>
      <CardHeader
        title={title}
        hint={hint}
        action={
          <SegmentedControl
            size="sm"
            value={view}
            onChange={setView}
            options={[
              { value: 'chart', label: 'Chart' },
              { value: 'table', label: 'Table' },
            ]}
          />
        }
      />

      {view === 'chart' ? (
        <SignedBarChart
          data={data}
          currency={currency}
          layout="horizontal"
          height={Math.max(160, data.length * 30)}
          valueLabel={
          metric === 'net_pnl' ? 'Net P&L' : metric === 'total_r' ? 'Total R' : 'Return'
        }
          formatValue={formatMetric}
          formatAxis={formatAxis}
        />
      ) : (
        <div className="-mx-1 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--tz-border)] text-left text-xs text-[var(--tz-text-muted)]">
                <th className="px-2 py-1.5 font-medium">Group</th>
                <th className="px-2 py-1.5 text-right font-medium">Trades</th>
                <th className="px-2 py-1.5 text-right font-medium">Win %</th>
                <th className="px-2 py-1.5 text-right font-medium">PF</th>
                <th className="px-2 py-1.5 text-right font-medium">Net</th>
                <th className="px-2 py-1.5 text-right font-medium">R</th>
                {/* Redundant once Net is itself a percentage. */}
                {accountSize > 0 && !hideMoney && (
                  <th className="px-2 py-1.5 text-right font-medium">% of acct</th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--tz-border)]">
              {rows.map((row) => (
                <tr key={row.key}>
                  <td className="px-2 py-1.5">{row.key}</td>
                  <td className="tabular px-2 py-1.5 text-right">{row.trades}</td>
                  <td className="tabular px-2 py-1.5 text-right">{percent(row.win_rate)}</td>
                  <td className="tabular px-2 py-1.5 text-right">
                    {profitFactor(row.profit_factor)}
                  </td>
                  <td className={clsx('tabular px-2 py-1.5 text-right', pnlClass(row.net_pnl))}>
                    {cash(row.net_pnl, { sign: true, decimals: 0 })}
                  </td>
                  <td className={clsx('tabular px-2 py-1.5 text-right', pnlClass(row.total_r))}>
                    {row.total_r === null ? '—' : `${num(row.total_r, 1)}R`}
                  </td>
                  {accountSize > 0 && !hideMoney && (
                    <td className={clsx('tabular px-2 py-1.5 text-right', pnlClass(row.net_pnl))}>
                      {row.net_pnl === null
                        ? '—'
                        : `${row.net_pnl > 0 ? '+' : ''}${num((row.net_pnl / accountSize) * 100, 2)}%`}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
