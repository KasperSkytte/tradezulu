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

type Metric = 'net_pnl' | 'total_r'

const SECTIONS: { key: keyof Breakdowns; title: string; hint: string }[] = [
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
  const { currency } = useSettings()
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

  const formatMetric = (value: number) =>
    metric === 'net_pnl' ? money(value, currency, { sign: true }) : `${num(value, 2)}R`

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
              { value: 'net_pnl', label: 'Money' },
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
                  formatMetric={formatMetric}
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
  formatMetric,
}: {
  title: string
  hint: string
  rows: BreakdownRow[]
  metric: Metric
  currency: string
  formatMetric: (value: number) => string
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
      value: (metric === 'net_pnl' ? row.net_pnl : row.total_r) ?? 0,
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
          valueLabel={metric === 'net_pnl' ? 'Net P&L' : 'Total R'}
          formatValue={formatMetric}
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
                    {money(row.net_pnl, currency, { sign: true, decimals: 0 })}
                  </td>
                  <td className={clsx('tabular px-2 py-1.5 text-right', pnlClass(row.total_r))}>
                    {row.total_r === null ? '—' : `${num(row.total_r, 1)}R`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
