import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Ban, Check, RotateCcw, Star, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import clsx from 'clsx'
import { api } from '../lib/api'
import { useSettings } from '../lib/settings'
import {
  dateTime,
  duration,
  money,
  num,
  pnlClass,
  price,
  rMultiple,
  timeOnly,
} from '../lib/format'
import type { Tag, TradeDetail } from '../lib/types'
import { TradeChart } from '../components/TradeChart'
import {
  Button,
  Card,
  CardHeader,
  DirectionBadge,
  ErrorState,
  Field,
  OutcomeBadge,
  Skeleton,
} from '../components/ui'

export function TradeDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { currency } = useSettings()

  const query = useQuery({
    queryKey: ['trade', id],
    queryFn: () => api.get<TradeDetail>(`/trades/${id}`),
    enabled: Boolean(id),
  })

  const { data: tags = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: () => api.get<Tag[]>('/tags'),
    staleTime: 300_000,
  })

  const update = useMutation({
    mutationFn: (patch: Record<string, unknown>) => api.patch<TradeDetail>(`/trades/${id}`, patch),
    onSuccess: (trade) => {
      queryClient.setQueryData(['trade', id], trade)
      void queryClient.invalidateQueries({ queryKey: ['trades'] })
      void queryClient.invalidateQueries({ queryKey: ['stats'] })
    },
  })

  const remove = useMutation({
    mutationFn: () => api.delete(`/trades/${id}`),
    onSuccess: () => {
      void queryClient.invalidateQueries()
      navigate('/trades')
    },
  })

  const trade = query.data

  // Notes are edited locally and saved explicitly so typing is never laggy.
  const [notes, setNotes] = useState('')
  const [setup, setSetup] = useState('')
  const [savedAt, setSavedAt] = useState<number | null>(null)

  useEffect(() => {
    if (!trade) return
    setNotes(trade.notes ?? '')
    setSetup(trade.setup ?? '')
  }, [trade?.id, trade])

  if (query.isError) return <ErrorState error={query.error} retry={() => void query.refetch()} />
  if (query.isLoading || !trade) return <Skeleton className="h-[70vh]" />

  const notesDirty = notes !== (trade.notes ?? '') || setup !== (trade.setup ?? '')

  return (
    <div className="space-y-4">
      {/* Header ---------------------------------------------------------- */}
      <div className="flex flex-wrap items-start gap-3">
        <Link to="/trades" className="tz-btn tz-btn-ghost">
          <ArrowLeft size={15} />
          <span className="hidden sm:inline">Trades</span>
        </Link>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">{trade.symbol}</h1>
            <DirectionBadge direction={trade.direction} />
            <OutcomeBadge outcome={trade.outcome} />
            {trade.excluded && (
              <span className="tz-chip bg-[var(--tz-surface-2)] text-[var(--tz-text-muted)]">
                <Ban size={11} /> Excluded from stats
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-[var(--tz-text-muted)]">
            {dateTime(trade.opened_at, undefined, trade.account_id)}
            {trade.closed_at && ` → ${timeOnly(trade.closed_at, trade.account_id)}`} · {num(trade.volume, 2)} lots ·
            held {duration(trade.duration_seconds)}
          </p>
        </div>

        <div className="text-right">
          <p className={clsx('tabular text-2xl font-semibold', pnlClass(trade.net_pnl))}>
            {money(trade.net_pnl, currency, { sign: true })}
          </p>
          <p className={clsx('tabular text-sm', pnlClass(trade.realized_r))}>
            {rMultiple(trade.realized_r)}
            {trade.planned_r !== null && (
              <span className="text-[var(--tz-text-muted)]">
                {' '}
                of {trade.planned_r.toFixed(1)}R planned
              </span>
            )}
          </p>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        {/* Chart ---------------------------------------------------------- */}
        <Card className="xl:col-span-2">
          <CardHeader
            title="Chart"
            hint="Entry, exit, stop and target are drawn from the trade itself. Every partial fill gets its own arrow."
          />
          <TradeChart trade={trade} />
        </Card>

        {/* Facts ---------------------------------------------------------- */}
        <div className="space-y-4">
          <Card>
            <CardHeader title="Execution" />
            <dl className="space-y-2 text-sm">
              <Row label="Entry" value={price(trade.entry_price, trade.digits)} />
              <Row label="Exit" value={price(trade.exit_price, trade.digits)} />
              <Row label="Volume" value={`${num(trade.volume, 2)} lots`} />
              <Row label="Gross" value={money(trade.gross_profit, currency, { sign: true })} />
              <Row label="Commission" value={money(trade.commission, currency)} />
              <Row label="Swap" value={money(trade.swap, currency)} />
              <Row
                label="Net"
                value={
                  <span className={pnlClass(trade.net_pnl)}>
                    {money(trade.net_pnl, currency, { sign: true })}
                  </span>
                }
              />
              <Row
                label="Source"
                value={
                  <span className="text-[var(--tz-text-muted)]">
                    {trade.source}
                    {trade.position_id > 0 && ` · #${trade.position_id}`}
                  </span>
                }
              />
            </dl>
          </Card>

          <Card>
            <CardHeader
              title="Plan & risk"
              hint="Change the stop or the target and every R figure for this trade is recalculated at once."
            />
            <div className="grid grid-cols-2 gap-3">
              <Field
                label="Initial stop"
                hint={
                  trade.stop_source === 'mt5'
                    ? 'Taken from the opening order in MetaTrader.'
                    : 'Set by you.'
                }
              >
                <NumberInput
                  value={trade.initial_stop}
                  digits={trade.digits}
                  onCommit={(value) =>
                    update.mutate(value === null ? { reset_stop: true } : { initial_stop: value })
                  }
                />
              </Field>
              <Field label="Initial target">
                <NumberInput
                  value={trade.initial_target}
                  digits={trade.digits}
                  onCommit={(value) =>
                    update.mutate(
                      value === null ? { reset_target: true } : { initial_target: value },
                    )
                  }
                />
              </Field>
              <Field
                label={`Risk (${currency})`}
                hint="Override when the stop in MetaTrader was not what you were actually risking."
              >
                <NumberInput
                  value={trade.risk_override ?? trade.risk_amount}
                  digits={2}
                  onCommit={(value) =>
                    update.mutate(value === null ? { reset_risk: true } : { risk_override: value })
                  }
                />
              </Field>
              <Field label="Rating">
                <StarRating
                  value={trade.rating}
                  onChange={(rating) => update.mutate({ rating })}
                />
              </Field>
            </div>

            <dl className="mt-3 space-y-2 border-t border-[var(--tz-border)] pt-3 text-sm">
              <Row label="Risk in money" value={money(trade.risk_amount, currency)} />
              <Row
                label="Planned R"
                value={trade.planned_r === null ? '—' : `${trade.planned_r.toFixed(2)}R`}
              />
              <Row
                label="Realised R"
                value={
                  <span className={pnlClass(trade.realized_r)}>{rMultiple(trade.realized_r)}</span>
                }
              />
              <Row
                label="Stop distance"
                value={
                  trade.initial_stop
                    ? price(Math.abs(trade.entry_price - trade.initial_stop), trade.digits)
                    : '—'
                }
              />
            </dl>

            <div className="mt-3 flex gap-2 border-t border-[var(--tz-border)] pt-3">
              <Button
                className="flex-1"
                icon={trade.excluded ? <RotateCcw size={14} /> : <Ban size={14} />}
                onClick={() => update.mutate({ excluded: !trade.excluded })}
              >
                {trade.excluded ? 'Include in stats' : 'Exclude from stats'}
              </Button>
              {trade.is_manual && (
                <Button
                  variant="danger"
                  icon={<Trash2 size={14} />}
                  loading={remove.isPending}
                  onClick={() => {
                    if (confirm('Delete this manually added trade?')) remove.mutate()
                  }}
                >
                  Delete
                </Button>
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* Journal ---------------------------------------------------------- */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title="Notes"
            action={
              <div className="flex items-center gap-2">
                {savedAt && !notesDirty && (
                  <span className="flex items-center gap-1 text-xs text-[var(--tz-gain-text)]">
                    <Check size={12} /> Saved
                  </span>
                )}
                <Button
                  variant="primary"
                  disabled={!notesDirty}
                  loading={update.isPending}
                  onClick={() => {
                    update.mutate({ notes, setup })
                    setSavedAt(Date.now())
                  }}
                >
                  Save
                </Button>
              </div>
            }
          />
          <Field label="Setup">
            <input
              className="tz-input"
              placeholder="What was the plan?"
              value={setup}
              onChange={(event) => setSetup(event.target.value)}
            />
          </Field>
          <textarea
            className="tz-input mt-3 min-h-44 leading-relaxed"
            placeholder={
              'What did you see, what did you do, and what would you do differently?\n\n' +
              'Tip: write this while the trade is still fresh — a week later you will only remember the P&L.'
            }
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
          />
        </Card>

        <Card>
          <CardHeader
            title="Tags"
            hint="Tags are how patterns surface. Reports groups every statistic by them."
          />
          <TagPicker
            tags={tags}
            selected={trade.tags.map((tag) => tag.id)}
            onChange={(tagIds) => update.mutate({ tag_ids: tagIds })}
          />
        </Card>
      </div>

      {/* Fills ------------------------------------------------------------ */}
      {trade.executions.length > 1 && (
        <Card padded={false}>
          <div className="px-4 pb-3 pt-4 sm:px-5">
            <h2 className="text-sm font-semibold tracking-tight">Fills</h2>
          </div>
          <div className="overflow-x-auto border-t border-[var(--tz-border)]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--tz-border)] text-left text-xs text-[var(--tz-text-muted)]">
                  <th className="px-4 py-2 font-medium">Time</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 text-right font-medium">Volume</th>
                  <th className="px-4 py-2 text-right font-medium">Price</th>
                  <th className="px-4 py-2 text-right font-medium">Profit</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--tz-border)]">
                {trade.executions.map((execution) => (
                  <tr key={execution.id}>
                    <td className="whitespace-nowrap px-4 py-2">{dateTime(execution.time, undefined, trade.account_id)}</td>
                    <td className="px-4 py-2">
                      <span className="tz-chip bg-[var(--tz-surface-2)]">
                        {execution.kind === 'in' ? 'Entry' : 'Exit'} · {execution.side}
                      </span>
                    </td>
                    <td className="tabular px-4 py-2 text-right">{num(execution.volume, 2)}</td>
                    <td className="tabular px-4 py-2 text-right">
                      {price(execution.price, trade.digits)}
                    </td>
                    <td className={clsx('tabular px-4 py-2 text-right', pnlClass(execution.profit))}>
                      {execution.profit ? money(execution.profit, currency, { sign: true }) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-[var(--tz-text-muted)]">{label}</dt>
      <dd className="tabular font-medium">{value}</dd>
    </div>
  )
}

function NumberInput({
  value,
  digits,
  onCommit,
}: {
  value: number | null
  digits: number
  onCommit: (value: number | null) => void
}) {
  const [draft, setDraft] = useState(value === null ? '' : String(value))

  useEffect(() => setDraft(value === null ? '' : String(value)), [value])

  return (
    <input
      type="number"
      step={10 ** -digits}
      className="tz-input"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => {
        const trimmed = draft.trim()
        if (trimmed === '' && value !== null) return onCommit(null)
        const parsed = Number(trimmed)
        if (Number.isFinite(parsed) && parsed !== value) onCommit(parsed)
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter') event.currentTarget.blur()
      }}
    />
  )
}

function StarRating({
  value,
  onChange,
}: {
  value: number | null
  onChange: (value: number | null) => void
}) {
  return (
    <div className="flex items-center gap-0.5 pt-1.5">
      {[1, 2, 3, 4, 5].map((star) => (
        <button
          key={star}
          type="button"
          aria-label={`Rate ${star} of 5`}
          onClick={() => onChange(value === star ? null : star)}
          className="transition-transform hover:scale-110"
        >
          <Star
            size={18}
            className={
              value !== null && star <= value
                ? 'fill-zulu-400 text-zulu-400'
                : 'text-[var(--tz-border-strong)]'
            }
          />
        </button>
      ))}
    </div>
  )
}

function TagPicker({
  tags,
  selected,
  onChange,
}: {
  tags: Tag[]
  selected: number[]
  onChange: (ids: number[]) => void
}) {
  const groups: { key: Tag['category']; label: string }[] = [
    { key: 'setup', label: 'Setup' },
    { key: 'mistake', label: 'Mistakes' },
    { key: 'emotion', label: 'Behaviour' },
    { key: 'custom', label: 'Other' },
  ]

  return (
    <div className="space-y-3">
      {groups.map((group) => {
        const groupTags = tags.filter((tag) => tag.category === group.key)
        if (!groupTags.length) return null
        return (
          <div key={group.key}>
            <p className="tz-label">{group.label}</p>
            <div className="flex flex-wrap gap-1.5">
              {groupTags.map((tag) => {
                const active = selected.includes(tag.id)
                return (
                  <button
                    key={tag.id}
                    type="button"
                    onClick={() =>
                      onChange(
                        active
                          ? selected.filter((item) => item !== tag.id)
                          : [...selected, tag.id],
                      )
                    }
                    className={clsx('tz-chip transition-all', !active && 'opacity-45 hover:opacity-80')}
                    style={{
                      backgroundColor: `color-mix(in srgb, ${tag.color} ${active ? 22 : 12}%, transparent)`,
                      color: tag.color,
                      border: `1px solid color-mix(in srgb, ${tag.color} ${active ? 55 : 25}%, transparent)`,
                    }}
                  >
                    {tag.name}
                  </button>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
