import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ChevronLeft, ChevronRight, NotebookPen } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  addMonths,
  eachDayOfInterval,
  endOfMonth,
  endOfWeek,
  format,
  isSameMonth,
  isToday,
  startOfMonth,
  startOfWeek,
} from 'date-fns'
import clsx from 'clsx'
import { api } from '../lib/api'
import { define } from '../lib/glossary'
import { useSettings } from '../lib/settings'
import { dateOnly, isoDate, money, num, percent, pnlClass, profitFactor } from '../lib/format'
import type { CalendarResponse, DayDetail, DailyPoint, Trade } from '../lib/types'
import { Dialog } from '../components/Dialog'
import { Button, Card, CardHeader, ErrorState, Hint, Skeleton } from '../components/ui'

export function CalendarPage() {
  const { currency, weekStartsOn } = useSettings()
  const queryClient = useQueryClient()
  const [cursor, setCursor] = useState(() => startOfMonth(new Date()))
  const [openDay, setOpenDay] = useState<string | null>(null)

  const month = format(cursor, 'yyyy-MM')
  const query = useQuery({
    queryKey: ['calendar', month],
    queryFn: () => api.get<CalendarResponse>('/stats/calendar', { month }),
  })

  const days = useMemo(() => {
    const map = new Map<string, DailyPoint>()
    for (const day of query.data?.days ?? []) map.set(String(day.date), day)
    return map
  }, [query.data])

  const grid = useMemo(() => {
    const start = startOfWeek(startOfMonth(cursor), { weekStartsOn })
    const end = endOfWeek(endOfMonth(cursor), { weekStartsOn })
    return eachDayOfInterval({ start, end })
  }, [cursor, weekStartsOn])

  const weekLabels = useMemo(() => {
    const start = startOfWeek(new Date(), { weekStartsOn })
    return Array.from({ length: 7 }, (_, index) =>
      format(new Date(start.getTime() + index * 86_400_000), 'EEEEEE'),
    )
  }, [weekStartsOn])

  const weekTotals = useMemo(() => {
    const map = new Map<string, { net: number; trades: number; days: number }>()
    for (const week of query.data?.weeks ?? []) {
      map.set(week.week_start, { net: week.net_pnl, trades: week.trades, days: week.days })
    }
    return map
  }, [query.data])

  const summary = query.data?.summary
  const openingBalance = query.data?.opening_balance ?? 0

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-1">
          <Button
            aria-label="Previous month"
            onClick={() => setCursor((value) => addMonths(value, -1))}
            className="px-2"
          >
            <ChevronLeft size={16} />
          </Button>
          <Button
            aria-label="Next month"
            onClick={() => setCursor((value) => addMonths(value, 1))}
            className="px-2"
          >
            <ChevronRight size={16} />
          </Button>
        </div>
        <h2 className="text-lg font-semibold tracking-tight">{format(cursor, 'MMMM yyyy')}</h2>
        <Button onClick={() => setCursor(startOfMonth(new Date()))} className="ml-1">
          Today
        </Button>

        {summary && (
          <div className="ml-auto flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
            <Stat label="Net P&L" value={money(summary.net_pnl, currency, { sign: true })} accent />
          {openingBalance > 0 && summary.net_pnl !== null && (
            <Stat
              label="Return"
              value={`${summary.net_pnl > 0 ? '+' : ''}${num(
                (summary.net_pnl / openingBalance) * 100,
                2,
              )}%`}
              accent
            />
          )}
            <Stat label="Trades" value={String(summary.counts.total)} />
            <Stat label="Win rate" value={percent(summary.win_rate)} />
            <Stat label="Profit factor" value={profitFactor(summary.profit_factor)} />
            <Stat
              label="Green days"
              value={`${summary.days.green}/${summary.days.total}`}
            />
          </div>
        )}
      </div>

      {query.isError ? (
        <ErrorState error={query.error} retry={() => void query.refetch()} />
      ) : query.isLoading ? (
        <Skeleton className="h-[560px]" />
      ) : (
        <Card padded={false} className="overflow-hidden">
          {/* Column headers: 7 day columns plus a weekly summary column. */}
          <div className="grid grid-cols-[repeat(7,minmax(0,1fr))] sm:grid-cols-[repeat(7,minmax(0,1fr))_minmax(0,0.85fr)] border-b border-[var(--tz-border)] text-xs font-medium text-[var(--tz-text-muted)]">
            {weekLabels.map((label) => (
              <div key={label} className="px-2 py-2 text-center">
                {label}
              </div>
            ))}
            <div className="hidden border-l border-[var(--tz-border)] px-2 py-2 text-center sm:block">Week</div>
          </div>

          <div className="grid grid-cols-[repeat(7,minmax(0,1fr))] sm:grid-cols-[repeat(7,minmax(0,1fr))_minmax(0,0.85fr)]">
            {chunk(grid, 7).map((week) => {
              const weekKey = isoDate(week[0])
              const total = weekTotals.get(weekKey)
              return (
                <div key={weekKey} className="contents">
                  {week.map((day) => {
                    const key = isoDate(day)
                    const entry = days.get(key)
                    const outside = !isSameMonth(day, cursor)
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setOpenDay(key)}
                        className={clsx(
                          'relative min-h-[5.5rem] border-b border-r border-[var(--tz-border)] p-1.5 text-left align-top transition-colors sm:min-h-[6.5rem] sm:p-2',
                          outside && 'opacity-40',
                          'hover:bg-[var(--tz-surface-hover)]',
                        )}
                        style={
                          entry && entry.trades > 0
                            ? {
                                backgroundColor: `color-mix(in srgb, ${
                                  entry.net_pnl > 0
                                    ? 'var(--tz-gain)'
                                    : entry.net_pnl < 0
                                      ? 'var(--tz-loss)'
                                      : 'var(--tz-flat)'
                                } ${Math.min(20, 6 + Math.abs(entry.net_pnl) / 60)}%, transparent)`,
                              }
                            : undefined
                        }
                      >
                        <div className="flex items-start justify-between">
                          <span
                            className={clsx(
                              'tabular text-xs',
                              isToday(day)
                                ? 'flex size-5 items-center justify-center rounded-full bg-zulu-500 font-semibold text-white'
                                : 'text-[var(--tz-text-muted)]',
                            )}
                          >
                            {format(day, 'd')}
                          </span>
                          {entry?.note && (
                            <NotebookPen size={11} className="text-[var(--tz-text-faint)]" />
                          )}
                        </div>

                        {entry && entry.trades > 0 && (
                          <div className="mt-1">
                            {/* The figure is signed, so the colour is never the only cue. */}
                            <p
                              className={clsx(
                                'tabular text-sm font-semibold leading-tight',
                                pnlClass(entry.net_pnl),
                              )}
                            >
                              {money(entry.net_pnl, currency, {
                                sign: true,
                                decimals: 0,
                                compact: true,
                              })}
                            </p>
                            {/* The day against what the account closed at the
                                day before: win 20 on a 200 account and that is
                                +10%. It reads directly under the money and at
                                the same weight, because it is the figure most
                                people actually judge a day by.

                                Three things and no more: money, percent, and
                                how many trades it took. R is not one of them --
                                a day's R is a sum of denominators that were
                                each a different size, and beside a real return
                                it reads as a second opinion nobody asked for.
                                No win rate either: a ratio of four trades is
                                noise wearing a percentage sign. */}
                            <p
                              className={clsx(
                                'tabular text-xs font-semibold leading-tight',
                                pnlClass(entry.net_pnl),
                              )}
                            >
                              {entry.return_pct != null ? (
                                <>
                                  {entry.return_pct > 0 ? '+' : ''}
                                  {num(entry.return_pct, 2)}%
                                </>
                              ) : (
                                <span className="text-[var(--tz-text-faint)]">—</span>
                              )}
                            </p>
                            <p className="mt-0.5 text-[0.65rem] text-[var(--tz-text-muted)]">
                              {entry.trades} trade{entry.trades === 1 ? '' : 's'}
                            </p>
                          </div>
                        )}
                      </button>
                    )
                  })}

                  <div className="hidden border-b border-[var(--tz-border)] bg-[var(--tz-bg-subtle)] p-2 sm:block">
                    {total && total.trades > 0 ? (
                      <>
                        <p className="text-[0.65rem] text-[var(--tz-text-muted)]">Week total</p>
                        <p
                          className={clsx(
                            'tabular text-sm font-semibold',
                            pnlClass(total.net),
                          )}
                        >
                          {money(total.net, currency, { sign: true, decimals: 0, compact: true })}
                        </p>
                        <p className="text-[0.65rem] text-[var(--tz-text-faint)]">
                          {total.days} day{total.days === 1 ? '' : 's'} · {total.trades}t
                        </p>
                      </>
                    ) : (
                      <p className="text-[0.65rem] text-[var(--tz-text-faint)]">—</p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </Card>
      )}

      {openDay && (
        <DayDialog
          day={openDay}
          onClose={() => setOpenDay(null)}
          onSaved={() => void queryClient.invalidateQueries({ queryKey: ['calendar'] })}
        />
      )}
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  const explain = define(label)
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="flex items-center gap-1 text-xs text-[var(--tz-text-muted)]">
        {label}
        {explain && <Hint text={explain} />}
      </span>
      <span
        className={clsx('tabular font-semibold', accent && pnlClass(Number(value.replace(/[^0-9.-]/g, ''))))}
      >
        {value}
      </span>
    </span>
  )
}

function DayDialog({
  day,
  onClose,
  onSaved,
}: {
  day: string
  onClose: () => void
  onSaved: () => void
}) {
  const { currency } = useSettings()
  const [note, setNote] = useState<string | null>(null)

  const query = useQuery({
    queryKey: ['day', day],
    queryFn: () => api.get<DayDetail>(`/stats/day/${day}`),
  })

  const tradesQuery = useQuery({
    queryKey: ['day-trades', day],
    queryFn: () =>
      api.get<{ items: Trade[] }>('/trades', {
        start: day,
        end: day,
        include_open: true,
        page_size: 100,
      }),
  })

  const saveNote = useMutation({
    mutationFn: (content: string) => api.put('/notes', { day, content, mood: '' }),
    onSuccess: () => {
      onSaved()
      onClose()
    },
  })

  const summary = query.data?.summary
  const current = note ?? query.data?.note?.content ?? ''

  return (
    <Dialog
      title={dateOnly(day, 'EEEE d MMMM yyyy')}
      onClose={onClose}
      size="lg"
      footer={
        <>
          <Button onClick={onClose}>Close</Button>
          <Button
            variant="primary"
            loading={saveNote.isPending}
            onClick={() => saveNote.mutate(current)}
          >
            Save note
          </Button>
        </>
      }
    >
      {query.isLoading ? (
        <Skeleton className="h-40" />
      ) : (
        <>
          {summary && summary.counts.total > 0 ? (
            <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <MiniStat
                label="Net P&L"
                value={money(summary.net_pnl, currency, { sign: true })}
                className={pnlClass(summary.net_pnl)}
              />
              {/* Against the balance the day opened with -- the same figure
                  as the cell that was clicked to get here. */}
              <MiniStat
                label="Net ROI"
                value={
                  query.data?.return_pct == null
                    ? '—'
                    : `${query.data.return_pct > 0 ? '+' : ''}${num(query.data.return_pct, 2)}%`
                }
                className={pnlClass(summary.net_pnl)}
              />
              <MiniStat label="Trades" value={String(summary.counts.total)} />
              <MiniStat label="Win rate" value={percent(summary.win_rate)} />
            </div>
          ) : (
            <p className="mb-4 text-sm text-[var(--tz-text-muted)]">No trades on this day.</p>
          )}

          {tradesQuery.data?.items.length ? (
            <div className="mb-4 divide-y divide-[var(--tz-border)] rounded-lg border border-[var(--tz-border)]">
              {tradesQuery.data.items.map((trade) => (
                <Link
                  key={trade.id}
                  to={`/trades/${trade.id}`}
                  className="flex items-center justify-between gap-3 px-3 py-2 text-sm transition-colors hover:bg-[var(--tz-surface-hover)]"
                  onClick={onClose}
                >
                  <span className="font-medium">{trade.symbol}</span>
                  <span className="text-xs text-[var(--tz-text-muted)]">{trade.direction}</span>
                  <span className={clsx('tabular ml-auto font-medium', pnlClass(trade.net_pnl))}>
                    {money(trade.net_pnl, currency, { sign: true })}
                  </span>
                </Link>
              ))}
            </div>
          ) : null}

          <CardHeader title="Day note" className="mb-2" />
          <textarea
            className="tz-input min-h-32"
            placeholder="How was the session? What was the market doing? What will you do differently tomorrow?"
            value={current}
            onChange={(event) => setNote(event.target.value)}
          />
        </>
      )}
    </Dialog>
  )
}

function MiniStat({
  label,
  value,
  className,
}: {
  label: string
  value: string
  className?: string
}) {
  const explain = define(label)
  return (
    <div className="rounded-lg bg-[var(--tz-surface-2)] px-3 py-2">
      <p className="flex items-center gap-1 text-xs text-[var(--tz-text-muted)]">
        {label}
        {explain && <Hint text={explain} />}
      </p>
      <p className={clsx('tabular mt-0.5 font-semibold', className)}>{value}</p>
    </div>
  )
}

function chunk<T>(items: T[], size: number): T[][] {
  const out: T[][] = []
  for (let index = 0; index < items.length; index += size) out.push(items.slice(index, index + size))
  return out
}
