import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Download, Inbox, Plus } from 'lucide-react'
import { useState } from 'react'
import clsx from 'clsx'
import { api } from '../lib/api'
import { BulkTagMenu } from '../components/BulkTagMenu'
import { useFilters } from '../lib/filters'
import { useSettings } from '../lib/settings'
import {
  dateOnly,
  duration,
  money,
  num,
  outcomeClass,
  pnlClass,
  price,
  rMultiple,
  timeOnly,
} from '../lib/format'
import type { Tag, Trade, TradePage as TradePageData } from '../lib/types'
import { FilterBar } from '../components/FilterBar'
import { ManualTradeDialog } from '../components/ManualTradeDialog'
import {
  Button,
  Card,
  DirectionBadge,
  EmptyState,
  ErrorState,
  OutcomeBadge,
  Skeleton,
} from '../components/ui'

type SortKey =
  | 'closed_at'
  | 'opened_at'
  | 'symbol'
  | 'net_pnl'
  | 'realized_r'
  | 'planned_r'
  | 'volume'
  | 'duration'
  | 'risk'

const COLUMNS: { key: SortKey | null; label: string; align?: 'right'; hideBelow?: string }[] = [
  { key: 'closed_at', label: 'Closed' },
  { key: 'symbol', label: 'Symbol' },
  { key: null, label: 'Side' },
  { key: 'volume', label: 'Size', align: 'right', hideBelow: 'xl' },
  { key: null, label: 'Entry → Exit', align: 'right', hideBelow: 'xl' },
  { key: 'risk', label: 'Risk', align: 'right', hideBelow: 'lg' },
  { key: 'planned_r', label: 'Plan', align: 'right', hideBelow: 'lg' },
  { key: 'realized_r', label: 'R', align: 'right' },
  { key: 'net_pnl', label: 'Net P&L', align: 'right' },
  { key: 'duration', label: 'Held', align: 'right', hideBelow: 'xl' },
  { key: null, label: 'Tags', hideBelow: 'lg' },
]

export function TradesPage() {
  const { params } = useFilters()
  const { currency } = useSettings()
  const queryClient = useQueryClient()

  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<SortKey>('closed_at')
  const [order, setOrder] = useState<'asc' | 'desc'>('desc')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [showManual, setShowManual] = useState(false)
  const pageSize = 50

  const query = useQuery({
    queryKey: ['trades', 'list', params, page, sort, order],
    queryFn: () =>
      api.get<TradePageData>('/trades', {
        ...params,
        page,
        page_size: pageSize,
        sort,
        order,
        include_open: true,
      }),
  })

  const { data: tags = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: () => api.get<Tag[]>('/tags'),
    staleTime: 300_000,
  })

  const bulkTag = useMutation({
    // Several tags, one request. The endpoint always took a list; only the
    // control in front of it insisted on one at a time.
    mutationFn: (tagIds: number[]) =>
      api.post('/trades/bulk', { trade_ids: [...selected], add_tag_ids: tagIds }),
    onSuccess: () => {
      setSelected(new Set())
      void queryClient.invalidateQueries({ queryKey: ['trades'] })
    },
  })

  function applySort(key: SortKey) {
    if (sort === key) setOrder(order === 'asc' ? 'desc' : 'asc')
    else {
      setSort(key)
      setOrder('desc')
    }
    setPage(1)
  }

  const data = query.data
  const totalPages = data ? Math.max(1, Math.ceil(data.total / pageSize)) : 1

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <FilterBar />
        <div className="ml-auto flex gap-2">
          <Button icon={<Plus size={15} />} onClick={() => setShowManual(true)}>
            <span className="hidden sm:inline">Add trade</span>
          </Button>
          <Button
            icon={<Download size={15} />}
            onClick={() =>
              void api.download('/trades/export.csv', params, 'tradezulu-trades.csv')
            }
          >
            <span className="hidden sm:inline">Export</span>
          </Button>
        </div>
      </div>

      {selected.size > 0 && (
        <Card className="tz-fade-in flex flex-wrap items-center gap-3 !py-3">
          <span className="text-sm font-medium">
            {selected.size} trade{selected.size === 1 ? '' : 's'} selected
          </span>
          <BulkTagMenu
            tags={tags}
            pending={bulkTag.isPending}
            onApply={(tagIds) => bulkTag.mutate(tagIds)}
          />
          <Button className="ml-auto" onClick={() => setSelected(new Set())}>
            Clear selection
          </Button>
        </Card>
      )}

      {query.isError ? (
        <ErrorState error={query.error} retry={() => void query.refetch()} />
      ) : query.isLoading || !data ? (
        <Skeleton className="h-96" />
      ) : data.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Inbox size={36} strokeWidth={1.4} />}
            title="No trades match these filters"
            description="Try a wider date range or clear the filters."
          />
        </Card>
      ) : (
        <>
          {/* Totals ------------------------------------------------------ */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <MiniStat label="Trades" value={String(data.total)} />
            <MiniStat
              label="Net P&L"
              value={money(data.totals.net_pnl, currency, { sign: true })}
              className={pnlClass(data.totals.net_pnl)}
            />
            <MiniStat label="Total R" value={rMultiple(data.totals.total_r)} />
            <MiniStat
              label="W / L / BE"
              value={`${data.totals.wins} / ${data.totals.losses} / ${data.totals.breakevens}`}
            />
          </div>

          {/* Desktop table ----------------------------------------------- */}
          <Card padded={false} className="hidden overflow-hidden md:block">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--tz-border)] text-left">
                    <th className="w-9 px-3 py-2.5">
                      <input
                        type="checkbox"
                        aria-label="Select all on this page"
                        className="size-3.5 accent-[var(--color-zulu-500)]"
                        checked={
                          data.items.length > 0 &&
                          data.items.every((trade) => selected.has(trade.id))
                        }
                        onChange={(event) =>
                          setSelected(
                            event.target.checked
                              ? new Set(data.items.map((trade) => trade.id))
                              : new Set(),
                          )
                        }
                      />
                    </th>
                    {COLUMNS.map((column) => (
                      <th
                        key={column.label}
                        className={clsx(
                          'px-3 py-2.5 text-xs font-medium text-[var(--tz-text-muted)]',
                          column.align === 'right' && 'text-right',
                          column.hideBelow === 'lg' && 'hidden lg:table-cell',
                          column.hideBelow === 'xl' && 'hidden xl:table-cell',
                        )}
                      >
                        {column.key ? (
                          <button
                            type="button"
                            onClick={() => applySort(column.key as SortKey)}
                            className={clsx(
                              'inline-flex items-center gap-1 transition-colors hover:text-[var(--tz-text)]',
                              sort === column.key && 'text-[var(--tz-text)]',
                            )}
                          >
                            {column.label}
                            {sort === column.key &&
                              (order === 'asc' ? <ArrowUp size={11} /> : <ArrowDown size={11} />)}
                          </button>
                        ) : (
                          column.label
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--tz-border)]">
                  {data.items.map((trade) => (
                    <TradeRow
                      key={trade.id}
                      trade={trade}
                      currency={currency}
                      selected={selected.has(trade.id)}
                      onToggle={() =>
                        setSelected((current) => {
                          const next = new Set(current)
                          if (next.has(trade.id)) next.delete(trade.id)
                          else next.add(trade.id)
                          return next
                        })
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* Mobile cards ------------------------------------------------ */}
          <div className="space-y-2 md:hidden">
            {data.items.map((trade) => (
              <TradeCard key={trade.id} trade={trade} currency={currency} />
            ))}
          </div>

          {/* Pagination -------------------------------------------------- */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between">
              <p className="text-xs text-[var(--tz-text-muted)]">
                Page {page} of {totalPages} · {data.total} trades
              </p>
              <div className="flex gap-2">
                <Button
                  icon={<ChevronLeft size={15} />}
                  disabled={page <= 1}
                  onClick={() => setPage((value) => value - 1)}
                >
                  Previous
                </Button>
                <Button
                  disabled={page >= totalPages}
                  onClick={() => setPage((value) => value + 1)}
                >
                  Next <ChevronRight size={15} />
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      {showManual && <ManualTradeDialog onClose={() => setShowManual(false)} />}
    </div>
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
  return (
    <div className="tz-card px-3 py-2.5">
      <p className="text-xs text-[var(--tz-text-muted)]">{label}</p>
      <p className={clsx('tabular mt-0.5 font-semibold', className)}>{value}</p>
    </div>
  )
}

function TradeRow({
  trade,
  currency,
  selected,
  onToggle,
}: {
  trade: Trade
  currency: string
  selected: boolean
  onToggle: () => void
}) {
  return (
    <tr
      className={clsx(
        'transition-colors hover:bg-[var(--tz-surface-hover)]',
        selected && 'bg-zulu-500/8',
        trade.excluded && 'opacity-55',
      )}
    >
      <td className="px-3 py-2">
        <input
          type="checkbox"
          aria-label={`Select trade ${trade.id}`}
          className="size-3.5 accent-[var(--color-zulu-500)]"
          checked={selected}
          onChange={onToggle}
        />
      </td>
      <td className="whitespace-nowrap px-3 py-2">
        <Link to={`/trades/${trade.id}`} className="block hover:text-zulu-400">
          <span className="block">{dateOnly(trade.closed_at ?? trade.opened_at, 'd MMM yy')}</span>
          <span className="text-xs text-[var(--tz-text-muted)]">
            {timeOnly(trade.closed_at ?? trade.opened_at)}
          </span>
        </Link>
      </td>
      <td className="px-3 py-2 font-medium">
        <Link to={`/trades/${trade.id}`} className="hover:text-zulu-400">
          {trade.symbol}
        </Link>
      </td>
      <td className="px-3 py-2">
        <DirectionBadge direction={trade.direction} />
      </td>
      <td className="tabular hidden px-3 py-2 text-right xl:table-cell">{num(trade.volume, 2)}</td>
      <td className="tabular hidden whitespace-nowrap px-3 py-2 text-right text-xs xl:table-cell">
        {price(trade.entry_price, trade.digits)}
        <span className="mx-1 text-[var(--tz-text-faint)]">→</span>
        {price(trade.exit_price, trade.digits)}
      </td>
      <td className="tabular hidden px-3 py-2 text-right lg:table-cell">
        {money(trade.risk_amount, currency, { decimals: 0 })}
      </td>
      <td className="tabular hidden px-3 py-2 text-right text-[var(--tz-text-muted)] lg:table-cell">
        {trade.planned_r === null ? '—' : `${trade.planned_r.toFixed(1)}R`}
      </td>
      <td className={clsx('tabular px-3 py-2 text-right font-medium', outcomeClass(trade.outcome, trade.realized_r))}>
        {rMultiple(trade.realized_r)}
      </td>
      <td className={clsx('tabular px-3 py-2 text-right font-semibold', outcomeClass(trade.outcome, trade.net_pnl))}>
        {money(trade.net_pnl, currency, { sign: true })}
      </td>
      <td className="tabular hidden px-3 py-2 text-right text-xs text-[var(--tz-text-muted)] xl:table-cell">
        {duration(trade.duration_seconds)}
      </td>
      <td className="hidden max-w-40 px-3 py-2 lg:table-cell">
        <div className="flex flex-wrap gap-1">
          {trade.tags.slice(0, 2).map((tag) => (
            <span
              key={tag.id}
              className="tz-chip"
              style={{
                backgroundColor: `color-mix(in srgb, ${tag.color} 18%, transparent)`,
                color: tag.color,
              }}
            >
              {tag.name}
            </span>
          ))}
          {trade.tags.length > 2 && (
            <span className="text-xs text-[var(--tz-text-faint)]">+{trade.tags.length - 2}</span>
          )}
        </div>
      </td>
    </tr>
  )
}

function TradeCard({ trade, currency }: { trade: Trade; currency: string }) {
  return (
    <Link
      to={`/trades/${trade.id}`}
      className={clsx('tz-card block p-3.5', trade.excluded && 'opacity-55')}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-semibold">{trade.symbol}</span>
            <DirectionBadge direction={trade.direction} />
            <OutcomeBadge outcome={trade.outcome} />
          </div>
          <p className="mt-1 text-xs text-[var(--tz-text-muted)]">
            {dateOnly(trade.closed_at ?? trade.opened_at, 'd MMM yyyy')} ·{' '}
            {timeOnly(trade.closed_at ?? trade.opened_at)} · {num(trade.volume, 2)} lots ·{' '}
            {duration(trade.duration_seconds)}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className={clsx('tabular font-semibold', outcomeClass(trade.outcome, trade.net_pnl))}>
            {money(trade.net_pnl, currency, { sign: true })}
          </p>
          <p className={clsx('tabular text-xs', outcomeClass(trade.outcome, trade.realized_r))}>
            {rMultiple(trade.realized_r)}
          </p>
        </div>
      </div>
      {trade.tags.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {trade.tags.map((tag) => (
            <span
              key={tag.id}
              className="tz-chip"
              style={{
                backgroundColor: `color-mix(in srgb, ${tag.color} 18%, transparent)`,
                color: tag.color,
              }}
            >
              {tag.name}
            </span>
          ))}
        </div>
      )}
      {trade.risk_amount !== null && (
        <p className="mt-2 text-xs text-[var(--tz-text-muted)]">
          Risked {money(trade.risk_amount, currency)}
          {trade.planned_r !== null && ` · planned ${trade.planned_r.toFixed(1)}R`}
        </p>
      )}
    </Link>
  )
}
