import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowUpRight, Ban, Inbox, TrendingUp } from 'lucide-react'
import { api } from '../lib/api'
import { useFilters } from '../lib/filters'
import { define } from '../lib/glossary'
import { useSettings } from '../lib/settings'
import {
  dateOnly,
  money,
  num,
  percent,
  pnlClass,
  profitFactor,
  rMultiple,
  timeOnly,
} from '../lib/format'
import type { Summary, Trade, TradePage } from '../lib/types'
import { CumulativeChart, OutcomeSplit, SignedBarChart } from '../components/charts'
import { Gauge, Sparkline, StatTile, WinLossBar } from '../components/StatTile'
import { ZuluScoreCard } from '../components/ZuluScoreCard'
import { Card, CardHeader, DirectionBadge, EmptyState, ErrorState, Hint, Skeleton } from '../components/ui'

export function DashboardPage() {
  const { params, filters } = useFilters()
  const { currency } = useSettings()

  const summaryQuery = useQuery({
    queryKey: ['stats', 'summary', params],
    queryFn: () => api.get<Summary>('/stats/summary', params),
  })

  const recentQuery = useQuery({
    queryKey: ['trades', 'recent', params],
    queryFn: () =>
      api.get<TradePage>('/trades', { ...params, page_size: 8, sort: 'closed_at', order: 'desc' }),
  })

  if (summaryQuery.isError) {
    return <ErrorState error={summaryQuery.error} retry={() => void summaryQuery.refetch()} />
  }

  if (summaryQuery.isLoading || !summaryQuery.data) return <DashboardSkeleton />

  const summary = summaryQuery.data
  const noTrades = summary.counts.total === 0 && summary.counts.open === 0

  if (noTrades) {
    return (
      <Card>
        <EmptyState
          icon={<Inbox size={38} strokeWidth={1.4} />}
          title="No trades in this period"
          description={
            <>
              Nothing was closed between {dateOnly(filters.start)} and {dateOnly(filters.end)}.
              Widen the date range, or connect MetaTrader 5 from{' '}
              <Link to="/settings#sync" className="text-zulu-400 underline underline-offset-2">
                Settings → MetaTrader 5
              </Link>
              .
            </>
          }
        />
      </Card>
    )
  }

  // Accumulate by day rather than by trade: several trades on one date would
  // otherwise repeat the same label along the x-axis.
  let running = 0
  const cumulative = summary.daily.map((day) => {
    running += day.net_pnl
    return {
      label: dateOnly(day.date, 'd MMM'),
      value: Math.round(running * 100) / 100,
      extra: `${day.trades} trade${day.trades === 1 ? '' : 's'} · ${money(day.net_pnl, currency, {
        sign: true,
      })} on the day`,
    }
  })

  const dailyBars = summary.daily.map((day) => ({
    label: dateOnly(day.date, 'd MMM'),
    value: day.net_pnl,
    meta: `${day.trades} trade${day.trades === 1 ? '' : 's'}${
      day.win_rate === null ? '' : ` · ${percent(day.win_rate)} win rate`
    }`,
  }))

  return (
    <div className="space-y-4">
      {/* KPI row --------------------------------------------------------- */}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
        <StatTile
          label="Net P&L"
          hint="Sum of every closed trade in the period, including commission and swap."
          value={money(summary.net_pnl, currency, { sign: true })}
          accent={
            (summary.net_pnl ?? 0) === 0
              ? undefined
              : (summary.net_pnl ?? 0) > 0
                ? 'var(--tz-gain-text)'
                : 'var(--tz-loss-text)'
          }
          sub={`${summary.counts.total} trades · ${rMultiple(summary.total_r)} total`}
          visual={
            // On a phone the tile is too narrow to hold both an exact P&L
            // figure and a sparkline, and the figure is what matters.
            <span className="hidden sm:block">
              <Sparkline values={cumulative.map((point) => point.value)} />
            </span>
          }
        />

        <StatTile
          label="Win rate"
          hint="Winners divided by winners plus losers. Breakevens are excluded by default — see Settings → Risk."
          value={percent(summary.win_rate)}
          sub={`${summary.counts.wins}W · ${summary.counts.losses}L · ${summary.counts.breakevens}BE`}
          visual={<Gauge value={summary.win_rate} />}
        />

        <StatTile
          label="Profit factor"
          hint="Gross profit divided by gross loss. Above 1 means the winners paid for the losers."
          value={profitFactor(summary.profit_factor)}
          sub={`Expectancy ${money(summary.expectancy, currency, { sign: true })}`}
          visual={
            <Gauge
              value={
                summary.profit_factor === null
                  ? null
                  : Math.min(100, (summary.profit_factor / 3) * 100)
              }
              color="var(--color-zulu-400)"
              track="var(--tz-border-strong)"
            />
          }
        />

        <StatTile
          label="Avg win/loss"
          hint="Average winning trade against the average losing trade, in money and in R."
          value={num(summary.payoff_ratio, 2)}
          sub={`${rMultiple(summary.avg_win_r)} vs ${rMultiple(summary.avg_loss_r)}`}
          visual={
            <WinLossBar
              win={summary.avg_win}
              loss={summary.avg_loss}
              formatValue={(value) => money(value, currency, { decimals: 0, compact: true })}
            />
          }
        />

        <StatTile
          label="Expectancy per trade"
          hint="Average R multiple across every scored trade. This is the number that compounds."
          value={rMultiple(summary.expectancy_r, 2)}
          accent={
            (summary.expectancy_r ?? 0) === 0
              ? undefined
              : (summary.expectancy_r ?? 0) > 0
                ? 'var(--tz-gain-text)'
                : 'var(--tz-loss-text)'
          }
          sub={`Avg risk ${money(summary.avg_risk, currency)}`}
          className="col-span-2 xl:col-span-1"
        />
      </div>

      {/* Score + charts -------------------------------------------------- */}
      <div className="grid gap-4 xl:grid-cols-3">
        <ZuluScoreCard score={summary.zulu_score} />

        <Card className="xl:col-span-2">
          <CardHeader
            title="Cumulative net P&L"
            hint="Net P&L accumulated day by day across the selected period."
            action={
              <span className={`tabular text-sm font-semibold ${pnlClass(summary.net_pnl)}`}>
                {money(summary.net_pnl, currency, { sign: true })}
              </span>
            }
          />
          <CumulativeChart data={cumulative} currency={currency} height={200} />

          <div className="mt-5 border-t border-[var(--tz-border)] pt-4">
            <CardHeader
              title="Net P&L by day"
              hint="Each bar is one trading day. Bars grow up for green days and down for red days."
              className="mb-3"
            />
            <SignedBarChart data={dailyBars} currency={currency} height={150} />
          </div>
        </Card>
      </div>

      {/* Secondary stats -------------------------------------------------- */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader title="Risk & consistency" />
          <dl className="space-y-2.5 text-sm">
            <Row
              label="Max drawdown"
              hint="Largest peak-to-trough fall in equity across the period."
              value={
                <span className="text-[var(--tz-loss-text)]">
                  {money(summary.max_drawdown ? -summary.max_drawdown : 0, currency)}
                  {summary.max_drawdown_pct !== null && (
                    <span className="ml-1 text-[var(--tz-text-muted)]">
                      ({percent(summary.max_drawdown_pct)})
                    </span>
                  )}
                </span>
              }
            />
            <Row
              label="Recovery factor"
              hint="Net profit divided by the maximum drawdown."
              value={num(summary.recovery_factor, 2)}
            />
            <Row
              label="Sharpe ratio"
              hint="Annualised risk-adjusted return from the daily P&L series."
              value={num(summary.sharpe, 2)}
            />
            <Row
              label="Sortino ratio"
              hint="Like Sharpe, but only downside volatility counts against you."
              value={num(summary.sortino, 2)}
            />
            <Row
              label="Consistency"
              hint="100% means profit was spread evenly across winning days; 0% means one day carried everything."
              value={percent(summary.consistency)}
            />
            <Row
              label="Kelly fraction"
              hint="Mathematically optimal risk per trade given this win rate and payoff. Most traders use a quarter of it."
              value={percent(summary.kelly)}
            />
          </dl>
        </Card>

        <Card>
          <CardHeader
            title="Outcome split"
            hint="Breakevens are wasted effort: they cost commission and attention but move nothing."
          />
          <OutcomeSplit
            wins={summary.counts.wins}
            losses={summary.counts.losses}
            breakevens={summary.counts.breakevens}
          />
          <dl className="mt-4 space-y-2.5 text-sm">
            <Row
              label="Breakeven trades"
              value={
                <span>
                  {summary.counts.breakevens}
                  <span className="ml-1 text-[var(--tz-text-muted)]">
                    ({percent(summary.breakeven_rate)})
                  </span>
                </span>
              }
            />
            <Row
              label="Breakeven P&L"
              value={money(summary.breakeven_pnl, currency, { sign: true })}
            />
            <Row label="Largest win" value={money(summary.largest_win, currency, { sign: true })} />
            <Row label="Largest loss" value={money(summary.largest_loss, currency)} />
            <Row
              label="Best streak"
              value={`${summary.streaks.max_win_streak}W / ${summary.streaks.max_loss_streak}L`}
            />
            <Row
              label="Green days"
              value={`${summary.days.green} of ${summary.days.total} (${percent(summary.days.win_rate)})`}
            />
          </dl>
        </Card>

        <Card>
          <CardHeader
            title="Plan vs execution"
            hint="How the R multiple you planned compares with what you actually banked."
          />
          <dl className="space-y-2.5 text-sm">
            <Row label="Average planned R" value={rMultiple(summary.avg_planned_r)} />
            <Row label="Average realised R" value={rMultiple(summary.avg_realized_r)} />
            <Row
              label="Plan adherence"
              hint="Realised R as a share of planned R. Under 100% means you are leaving the plan early."
              value={percent(summary.plan_adherence)}
            />
            <Row label="Average hold time" value={formatSeconds(summary.durations.avg)} />
            <Row label="Winners held" value={formatSeconds(summary.durations.avg_win)} />
            <Row label="Losers held" value={formatSeconds(summary.durations.avg_loss)} />
            {summary.counts.excluded > 0 && (
              <Row
                label="Excluded from stats"
                value={
                  <span className="flex items-center gap-1 text-[var(--tz-text-muted)]">
                    <Ban size={12} />
                    {summary.counts.excluded}
                  </span>
                }
              />
            )}
          </dl>
        </Card>
      </div>

      {/* Recent trades ---------------------------------------------------- */}
      <Card padded={false}>
        <div className="flex items-center justify-between px-4 pb-3 pt-4 sm:px-5">
          <h2 className="text-sm font-semibold tracking-tight">Recent trades</h2>
          <Link
            to="/trades"
            className="flex items-center gap-1 text-xs text-[var(--tz-text-muted)] transition-colors hover:text-[var(--tz-text)]"
          >
            All trades <ArrowUpRight size={13} />
          </Link>
        </div>
        {recentQuery.data?.items.length ? (
          <RecentTradeList trades={recentQuery.data.items} currency={currency} />
        ) : (
          <EmptyState icon={<TrendingUp size={30} strokeWidth={1.4} />} title="Nothing yet" />
        )}
      </Card>
    </div>
  )
}

function Row({
  label,
  value,
  hint,
}: {
  label: string
  value: React.ReactNode
  hint?: string
}) {
  const explain = hint ?? define(label)
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="flex items-center gap-1.5 text-[var(--tz-text-muted)]">
        {label}
        {explain && <Hint text={explain} />}
      </dt>
      <dd className="tabular font-medium">{value}</dd>
    </div>
  )
}

function RecentTradeList({ trades, currency }: { trades: Trade[]; currency: string }) {
  return (
    <div className="divide-y divide-[var(--tz-border)] border-t border-[var(--tz-border)]">
      {trades.map((trade) => (
        <Link
          key={trade.id}
          to={`/trades/${trade.id}`}
          className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-[var(--tz-surface-hover)] sm:px-5"
        >
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate font-medium">{trade.symbol}</span>
              <DirectionBadge direction={trade.direction} />
            </div>
            <p className="mt-0.5 text-xs text-[var(--tz-text-muted)]">
              {dateOnly(trade.closed_at ?? trade.opened_at, 'd MMM')} ·{' '}
              {timeOnly(trade.closed_at ?? trade.opened_at)} · {num(trade.volume, 2)} lots
            </p>
          </div>
          <div className="text-right">
            <p className={`tabular font-semibold ${pnlClass(trade.net_pnl)}`}>
              {money(trade.net_pnl, currency, { sign: true })}
            </p>
            <p className="tabular text-xs text-[var(--tz-text-muted)]">
              {rMultiple(trade.realized_r)}
            </p>
          </div>
        </Link>
      ))}
    </div>
  )
}

function formatSeconds(seconds: number | null) {
  if (seconds === null) return '—'
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`
  const hours = seconds / 3600
  return hours < 24 ? `${hours.toFixed(1)} h` : `${(hours / 24).toFixed(1)} d`
}

function DashboardSkeleton() {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
        {Array.from({ length: 5 }).map((_, index) => (
          <Skeleton key={index} className="h-[86px]" />
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Skeleton className="h-[520px]" />
        <Skeleton className="h-[520px] xl:col-span-2" />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className="h-56" />
        ))}
      </div>
    </div>
  )
}
