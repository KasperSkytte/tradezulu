import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  Check,

  Database,
  Download,
  Gauge,
  Palette,
  Plug,
  RefreshCw,
  Shield,
  SlidersHorizontal,
  Tags as TagsIcon,
  Trash2,
  Upload,
} from 'lucide-react'
import clsx from 'clsx'
import { ApiError, api } from '../lib/api'
import { useSettings } from '../lib/settings'
import type { DeepPartial } from '../lib/settings'
import { money, num, relative } from '../lib/format'
import { PERIOD_OPTIONS } from '../lib/period'
import type { Account, AppSettings, SyncStatus, SystemInfo, Tag } from '../lib/types'
import { Button, Card, CardHeader, Field, SegmentedControl, Skeleton, Toggle } from '../components/ui'
import { MT5Account } from '../components/MT5Account'

const SECTIONS = [
  { id: 'general', label: 'General', icon: Palette },
  { id: 'risk', label: 'Risk & R', icon: SlidersHorizontal },
  { id: 'score', label: 'Zulu Score', icon: Gauge },
  { id: 'sync', label: 'MetaTrader 5', icon: Plug },
  { id: 'tags', label: 'Tags', icon: TagsIcon },
  { id: 'account', label: 'Account', icon: Database },
  { id: 'security', label: 'Security', icon: Shield },
] as const

type SectionId = (typeof SECTIONS)[number]['id']

function sectionFromHash(): SectionId | null {
  const hash = window.location.hash.replace('#', '')
  return SECTIONS.find((entry) => entry.id === hash)?.id ?? null
}

export function SettingsPage() {
  const [section, setSection] = useState<SectionId>(() => sectionFromHash() ?? 'general')
  const { loading } = useSettings()

  useEffect(() => {
    window.history.replaceState(null, '', `#${section}`)
  }, [section])

  // Links such as /settings#sync must land on the right section even when the
  // page is already open, which is only a hash change and not a remount.
  useEffect(() => {
    const onHashChange = () => {
      const next = sectionFromHash()
      if (next) setSection(next)
    }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, [])

  if (loading) return <Skeleton className="h-[70vh]" />

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      <nav className="flex shrink-0 gap-1 overflow-x-auto lg:w-48 lg:flex-col">
        {SECTIONS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            type="button"
            onClick={() => setSection(id)}
            className={clsx(
              'flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
              section === id
                ? 'bg-zulu-500/12 text-zulu-400'
                : 'text-[var(--tz-text-muted)] hover:bg-[var(--tz-surface-hover)] hover:text-[var(--tz-text)]',
            )}
          >
            <Icon size={16} strokeWidth={1.9} />
            {label}
          </button>
        ))}
      </nav>

      <div className="min-w-0 flex-1 space-y-4">
        {section === 'general' && <GeneralSection />}
        {section === 'risk' && <RiskSection />}
        {section === 'score' && <ScoreSection />}
        {section === 'sync' && <SyncSection />}
        {section === 'tags' && <TagsSection />}
        {section === 'account' && <AccountSection />}
        {section === 'security' && <SecuritySection />}
      </div>
    </div>
  )
}

/* --------------------------------------------------------------------- */

function useSaver() {
  const { save } = useSettings()
  const [saved, setSaved] = useState(false)

  return {
    saved,
    apply: async (patch: DeepPartial<AppSettings>) => {
      await save(patch)
      setSaved(true)
      setTimeout(() => setSaved(false), 1800)
    },
  }
}

function SavedFlag({ saved }: { saved: boolean }) {
  if (!saved) return null
  return (
    <span className="flex items-center gap-1 text-xs text-[var(--tz-gain-text)]">
      <Check size={12} /> Saved
    </span>
  )
}

const TIMEZONES = [
  'UTC',
  'Europe/Copenhagen',
  'Europe/London',
  'Europe/Berlin',
  'Europe/Stockholm',
  'America/New_York',
  'America/Chicago',
  'America/Los_Angeles',
  'Asia/Tokyo',
  'Asia/Singapore',
  'Australia/Sydney',
]

function GeneralSection() {
  const { settings } = useSettings()
  const { apply, saved } = useSaver()
  const general = settings.general

  return (
    <Card>
      <CardHeader title="General" action={<SavedFlag saved={saved} />} />
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Timezone"
          hint="Decides which calendar day a trade belongs to. Use your own trading day, not the broker's."
        >
          <select
            className="tz-input"
            value={general.timezone}
            onChange={(event) => void apply({ general: { timezone: event.target.value } })}
          >
            {[...new Set([general.timezone, ...TIMEZONES])].map((zone) => (
              <option key={zone} value={zone}>
                {zone}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Currency symbol">
          <input
            className="tz-input"
            defaultValue={general.currency_symbol}
            onBlur={(event) =>
              void apply({ general: { currency_symbol: event.target.value || '$' } })
            }
          />
        </Field>

        <Field label="Week starts on">
          <SegmentedControl
            value={general.week_starts_on}
            onChange={(value) => void apply({ general: { week_starts_on: value } })}
            options={[
              { value: 'monday', label: 'Monday' },
              { value: 'sunday', label: 'Sunday' },
            ]}
          />
        </Field>

        <Field label="Default period" hint="What the date picker starts on when you open the app.">
          <select
            className="tz-input"
            value={general.default_period}
            onChange={(event) => void apply({ general: { default_period: event.target.value } })}
          >
            {PERIOD_OPTIONS.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>

        <Field label="Theme">
          <SegmentedControl
            value={general.theme}
            onChange={(value) => void apply({ general: { theme: value } })}
            options={[
              { value: 'dark', label: 'Dark' },
              { value: 'light', label: 'Light' },
              { value: 'system', label: 'System' },
            ]}
          />
        </Field>
      </div>

      <div className="mt-4 border-t border-[var(--tz-border)] pt-2">
        <Toggle
          label="Colour-blind friendly results"
          description="Uses blue for profit and amber for loss instead of green and red. Both pairs stay distinguishable with any form of colour blindness."
          checked={general.colorblind_mode}
          onChange={(value) => void apply({ general: { colorblind_mode: value } })}
        />
      </div>
    </Card>
  )
}

/* --------------------------------------------------------------------- */

function RiskSection() {
  const { settings, currency } = useSettings()
  const { apply, saved } = useSaver()
  const risk = settings.risk
  const stats = settings.stats

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Breakevens"
          hint="A trade that ends within a whisker of your entry cost you commission and attention but produced nothing. TradeZulu counts these separately so they cannot flatter your win rate."
          action={<SavedFlag saved={saved} />}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Breakeven threshold (R)"
            hint="Any closed trade whose realised R is smaller than this, in either direction, is a breakeven."
          >
            <NumberField
              value={risk.breakeven_threshold_r}
              step={0.01}
              onCommit={(value) => void apply({ risk: { breakeven_threshold_r: value } })}
            />
          </Field>
          <Field
            label={`Breakeven threshold (${currency})`}
            hint="Used only when a trade has no known risk, so no R can be computed."
          >
            <NumberField
              value={risk.breakeven_threshold_money}
              step={0.5}
              onCommit={(value) => void apply({ risk: { breakeven_threshold_money: value } })}
            />
          </Field>
          <Field
            label="Breakeven threshold (% of account)"
            hint="A third way of saying the same thing, for people who think in percent. Any threshold calling a trade breakeven is enough — they are alternatives, not conditions to satisfy together. 0 turns it off."
          >
            <NumberField
              value={risk.breakeven_threshold_percent}
              step={0.05}
              onCommit={(value) => void apply({ risk: { breakeven_threshold_percent: value } })}
            />
          </Field>
          <Field label="How breakevens count" className="sm:col-span-2">
            <SegmentedControl
              value={risk.breakeven_handling}
              onChange={(value) => void apply({ risk: { breakeven_handling: value } })}
              options={[
                { value: 'excluded', label: 'Excluded (recommended)' },
                { value: 'loss', label: 'As losses' },
                { value: 'win', label: 'As wins' },
              ]}
            />
          </Field>
        </div>
      </Card>

      <Card>
        <CardHeader
          title="Risk per trade"
          hint="R is money risked. When MetaTrader reports the stop loss on the entry order, TradeZulu uses it; these settings decide what happens when it does not."
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="When no stop loss was recorded" className="sm:col-span-2">
            <select
              className="tz-input"
              value={risk.fallback_risk_mode}
              onChange={(event) =>
                void apply({
                  risk: { fallback_risk_mode: event.target.value as typeof risk.fallback_risk_mode },
                })
              }
            >
              <option value="percent_of_balance">Assume a percentage of the account</option>
              <option value="fixed_amount">Assume a fixed amount</option>
              <option value="none">Leave the trade without an R multiple</option>
            </select>
          </Field>

          <Field label="Assumed risk (% of account)">
            <NumberField
              value={risk.risk_percent}
              step={0.05}
              disabled={risk.fallback_risk_mode !== 'percent_of_balance'}
              onCommit={(value) => void apply({ risk: { risk_percent: value } })}
            />
          </Field>
          <Field label={`Assumed risk (${currency})`}>
            <NumberField
              value={risk.fixed_risk_amount}
              step={5}
              disabled={risk.fallback_risk_mode !== 'fixed_amount'}
              onCommit={(value) => void apply({ risk: { fixed_risk_amount: value } })}
            />
          </Field>

        </div>

        <div className="mt-2 border-t border-[var(--tz-border)] pt-2">
          <Toggle
            label="Include commission in P&L"
            checked={risk.include_commission_in_pnl}
            onChange={(value) => void apply({ risk: { include_commission_in_pnl: value } })}
          />
          <Toggle
            label="Include swap in P&L"
            checked={risk.include_swap_in_pnl}
            onChange={(value) => void apply({ risk: { include_swap_in_pnl: value } })}
          />
          <Toggle
            label="R multiples use net P&L"
            description="On, costs count against your R. Off, R is measured on the gross result."
            checked={risk.r_uses_net_pnl}
            onChange={(value) => void apply({ risk: { r_uses_net_pnl: value } })}
          />
        </div>
      </Card>

      <Card>
        <CardHeader title="Statistics" />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Risk-free rate (% per year)" hint="Subtracted from returns in Sharpe.">
            <NumberField
              value={stats.risk_free_rate}
              step={0.1}
              onCommit={(value) => void apply({ stats: { risk_free_rate: value } })}
            />
          </Field>
          <Field label="Trading days per year" hint="Used to annualise Sharpe and Sortino.">
            <NumberField
              value={stats.trading_days_per_year}
              step={1}
              onCommit={(value) => void apply({ stats: { trading_days_per_year: value } })}
            />
          </Field>
          <Field label="Sharpe basis">
            <SegmentedControl
              value={stats.sharpe_basis}
              onChange={(value) => void apply({ stats: { sharpe_basis: value } })}
              options={[
                { value: 'daily', label: 'Per day' },
                { value: 'trade', label: 'Per trade' },
              ]}
            />
          </Field>
          <Field
            label="Minimum trades for a meaningful score"
            hint="Below this the Zulu Score is still shown but flagged as a small sample."
          >
            <NumberField
              value={stats.min_trades_for_score}
              step={1}
              onCommit={(value) => void apply({ stats: { min_trades_for_score: value } })}
            />
          </Field>
        </div>
      </Card>
    </div>
  )
}

/* --------------------------------------------------------------------- */

const SCORE_COMPONENTS = [
  { key: 'win_rate', label: 'Win rate', unit: '%', hint: 'Win rate that scores 100.' },
  { key: 'profit_factor', label: 'Profit factor', unit: '', hint: 'Profit factor that scores 100.' },
  { key: 'avg_win_loss', label: 'Avg win / loss', unit: '', hint: 'Payoff ratio that scores 100.' },
  {
    key: 'max_drawdown',
    label: 'Max drawdown',
    unit: '%',
    hint: 'Drawdown at which this component scores 0. Lower drawdown scores higher.',
  },
  { key: 'recovery_factor', label: 'Recovery factor', unit: '', hint: 'Recovery factor that scores 100.' },
  { key: 'consistency', label: 'Consistency', unit: '%', hint: 'Consistency that scores 100.' },
] as const

function ScoreSection() {
  const { settings } = useSettings()
  const { apply, saved } = useSaver()
  const score = settings.zulu_score

  return (
    <Card>
      <CardHeader
        title="Zulu Score"
        hint="Each component is scored 0-100 against its target, then averaged using the weights. Set a weight to 0 to drop a component entirely."
        action={<SavedFlag saved={saved} />}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--tz-border)] text-left text-xs text-[var(--tz-text-muted)]">
              <th className="py-2 font-medium">Component</th>
              <th className="py-2 font-medium">Target</th>
              <th className="py-2 font-medium">Weight</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--tz-border)]">
            {SCORE_COMPONENTS.map((component) => (
              <tr key={component.key}>
                <td className="py-2 pr-3">
                  <span className="font-medium">{component.label}</span>
                  <span className="mt-0.5 block text-xs text-[var(--tz-text-muted)]">
                    {component.hint}
                  </span>
                </td>
                <td className="w-28 py-2 pr-3">
                  <div className="flex items-center gap-1">
                    <NumberField
                      value={score.targets[component.key] ?? 0}
                      step={component.unit === '%' ? 1 : 0.1}
                      onCommit={(value) =>
                        void apply({ zulu_score: { targets: { [component.key]: value } } })
                      }
                    />
                    {component.unit && (
                      <span className="text-xs text-[var(--tz-text-muted)]">{component.unit}</span>
                    )}
                  </div>
                </td>
                <td className="w-24 py-2">
                  <NumberField
                    value={score.weights[component.key] ?? 0}
                    step={0.5}
                    onCommit={(value) =>
                      void apply({ zulu_score: { weights: { [component.key]: value } } })
                    }
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

/* --------------------------------------------------------------------- */

function SyncSection() {
  const { settings, currency } = useSettings()
  const { apply, saved } = useSaver()
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [importResult, setImportResult] = useState<string | null>(null)
  const [importError, setImportError] = useState<string | null>(null)

  const { data: status } = useQuery({
    queryKey: ['sync-status'],
    queryFn: () => api.get<SyncStatus>('/mt5/status'),
    // Poll while a terminal is being built, so "starting" turns into "running"
    // on its own. Without this the message is written once and sits there,
    // which reads as stuck rather than working.
    refetchInterval: (query) =>
      query.state.data?.phase === 'starting' || query.state.data?.phase === 'stalled'
        ? 5000
        : false,
  })
  const { data: system } = useQuery({
    queryKey: ['system'],
    queryFn: () => api.get<SystemInfo>('/settings/system'),
  })

  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.upload<{ created: number; updated: number; kind: string }>('/import/file', form)
    },
    onSuccess: (result) => {
      setImportError(null)
      setImportResult(
        `Imported ${result.created} new and updated ${result.updated} existing trades from the ${result.kind === 'mt5_html' ? 'MetaTrader report' : 'CSV'}.`,
      )
      void queryClient.invalidateQueries()
    },
    onError: (error) => {
      setImportResult(null)
      setImportError(error instanceof ApiError ? error.message : 'Import failed')
    },
  })

  const rebuild = useMutation({
    mutationFn: () => api.post<{ trades: number }>('/mt5/rebuild'),
    onSuccess: () => void queryClient.invalidateQueries(),
  })

  const recompute = useMutation({
    mutationFn: () => api.post<{ recomputed: number }>('/settings/recompute'),
    onSuccess: () => void queryClient.invalidateQueries(),
  })


  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Connection" action={<SavedFlag saved={saved} />} />

        {status && (
          <div className="mb-4 grid gap-3 rounded-lg bg-[var(--tz-surface-2)] p-3 sm:grid-cols-4">
            <Fact label="Account" value={status.login && status.login !== '0' ? status.login : '—'} />
            <Fact label="Balance" value={money(status.balance, currency)} />
            <Fact label="Trades" value={String(status.total_trades)} />
            <Fact label="Last sync" value={status.last_sync_at ? relative(status.last_sync_at) : 'never'} />
          </div>
        )}

        <Field
          label="How deals reach TradeZulu"
          hint="A terminal is started for your account automatically and its Expert Advisor reports in. Manual import is there for history from anywhere else."
        >
          <SegmentedControl
            value={settings.mt5.sync_mode}
            onChange={(value) => void apply({ mt5: { sync_mode: value } })}
            options={[
              { value: 'ea', label: 'Automatic' },
              { value: 'off', label: 'Manual import' },
            ]}
          />
        </Field>
        {settings.mt5.sync_mode === 'ea' && (
          <div className="mt-4 space-y-4">
            <MT5Account status={status} />

            <Toggle
              label="Refresh automatically while the journal is open"
              checked={settings.mt5.auto_sync_on_load}
              onChange={(value) => void apply({ mt5: { auto_sync_on_load: value } })}
            />

            {status?.connected ? (
              <p className="flex items-center gap-1.5 text-sm text-[var(--tz-gain-text)]">
                <Check size={14} /> Terminal is running and logged in.
              </p>
            ) : status?.message ? (
              <p className="text-sm text-[var(--tz-text-muted)]">{status.message}</p>
            ) : null}

            {system && !system.ingest_token_configured && (
              <p className="flex items-center gap-1.5 text-sm text-[var(--tz-loss-text)]">
                <AlertTriangle size={14} /> TZ_INGEST_TOKEN is not set on the server, so the
                terminal cannot authenticate yet.
              </p>
            )}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader
          title="Import a file"
          hint="For history the Expert Advisor cannot see, or if you would rather not run one at all."
        />
        <p className="mb-3 text-sm text-[var(--tz-text-muted)]">
          In MetaTrader 5: <strong>Toolbox → History</strong>, right-click → <strong>Report</strong>{' '}
          → save as HTML, then drop it here. Plain CSV exports work too, as long as they have symbol,
          open time and price columns.
        </p>
        <input
          ref={fileInput}
          type="file"
          accept=".html,.htm,.csv,.txt"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) upload.mutate(file)
            event.target.value = ''
          }}
        />
        <div className="flex flex-wrap gap-2">
          <Button
            variant="primary"
            icon={<Upload size={15} />}
            loading={upload.isPending}
            onClick={() => fileInput.current?.click()}
          >
            Choose a file
          </Button>
          <Button
            icon={<Download size={15} />}
            onClick={() =>
              void api.download('/trades/export.csv', { period: 'all' }, 'tradezulu-all-trades.csv')
            }
          >
            Export everything as CSV
          </Button>
        </div>
        {importResult && (
          <p className="mt-3 text-sm text-[var(--tz-gain-text)]">{importResult}</p>
        )}
        {importError && <p className="mt-3 text-sm text-[var(--tz-loss-text)]">{importError}</p>}
      </Card>

      <Card>
        <CardHeader
          title="Maintenance"
          hint="Neither of these can lose anything: notes, tags and manual overrides are always preserved."
        />
        <div className="flex flex-wrap gap-2">
          <Button
            icon={<RefreshCw size={15} />}
            loading={rebuild.isPending}
            onClick={() => rebuild.mutate()}
          >
            Rebuild trades from stored deals
          </Button>
          <Button
            icon={<RefreshCw size={15} />}
            loading={recompute.isPending}
            onClick={() => recompute.mutate()}
          >
            Recompute all statistics
          </Button>
        </div>
        {rebuild.isSuccess && (
          <p className="mt-2 text-sm text-[var(--tz-text-muted)]">
            Rebuilt {rebuild.data.trades} trades.
          </p>
        )}
        {recompute.isSuccess && (
          <p className="mt-2 text-sm text-[var(--tz-text-muted)]">
            Recomputed {recompute.data.recomputed} trades.
          </p>
        )}
        {system && (
          <dl className="mt-4 space-y-1.5 border-t border-[var(--tz-border)] pt-3 text-sm">
            <Fact inline label="Version" value={system.version} />
            <Fact inline label="Data directory" value={system.data_dir} />
            <Fact inline label="Trades stored" value={String(system.trades)} />
            {system.secret_key_ephemeral && (
              <p className="flex items-center gap-1.5 pt-1 text-[var(--tz-loss-text)]">
                <AlertTriangle size={14} /> TZ_SECRET_KEY is unset — you will be logged out on every
                restart.
              </p>
            )}
          </dl>
        )}
      </Card>

      <Card>
        <CardHeader title="Charts" />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Default chart"
            hint="Replay uses candles TradeZulu stores and can mark your actual fills. TradingView has the full toolset but knows nothing about your trade."
          >
            <SegmentedControl
              value={settings.charts.provider}
              onChange={(value) => void apply({ charts: { provider: value } })}
              options={[
                { value: 'local', label: 'Replay' },
                { value: 'tradingview', label: 'TradingView' },
              ]}
            />
          </Field>
          <Field label="Default timeframe">
            <select
              className="tz-input"
              value={settings.charts.default_timeframe}
              onChange={(event) =>
                void apply({ charts: { default_timeframe: event.target.value } })
              }
            >
              {['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1'].map((timeframe) => (
                <option key={timeframe}>{timeframe}</option>
              ))}
            </select>
          </Field>
          <Field label="Candles before entry">
            <NumberField
              value={settings.charts.candles_before}
              step={10}
              onCommit={(value) => void apply({ charts: { candles_before: value } })}
            />
          </Field>
          <Field label="Candles after exit">
            <NumberField
              value={settings.charts.candles_after}
              step={10}
              onCommit={(value) => void apply({ charts: { candles_after: value } })}
            />
          </Field>
          <Field
            label="TradingView exchange prefix"
            hint="For example OANDA: or FX: — prepended to your broker's symbol."
            className="sm:col-span-2"
          >
            <input
              className="tz-input"
              placeholder="OANDA:"
              defaultValue={settings.charts.tradingview_prefix}
              onBlur={(event) =>
                void apply({ charts: { tradingview_prefix: event.target.value } })
              }
            />
          </Field>
        </div>
      </Card>
    </div>
  )
}

function Fact({
  label,
  value,
  inline,
}: {
  label: string
  value: string
  inline?: boolean
}) {
  if (inline) {
    return (
      <div className="flex justify-between gap-3">
        <dt className="text-[var(--tz-text-muted)]">{label}</dt>
        <dd className="truncate font-medium">{value}</dd>
      </div>
    )
  }
  return (
    <div>
      <p className="text-xs text-[var(--tz-text-muted)]">{label}</p>
      <p className="tabular mt-0.5 font-semibold">{value}</p>
    </div>
  )
}
const TAG_CATEGORIES = [
  { value: 'setup', label: 'Setup' },
  { value: 'mistake', label: 'Mistake' },
  { value: 'emotion', label: 'Behaviour' },
  { value: 'custom', label: 'Other' },
]

function TagsSection() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [color, setColor] = useState('#7c5cff')
  const [category, setCategory] = useState('mistake')
  const [error, setError] = useState<string | null>(null)

  const { data: tags = [], isLoading } = useQuery({
    queryKey: ['tags'],
    queryFn: () => api.get<Tag[]>('/tags'),
  })
  const { data: usage = {} } = useQuery({
    queryKey: ['tag-usage'],
    queryFn: () => api.get<Record<string, number>>('/tags/usage'),
  })

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['tags'] })
    void queryClient.invalidateQueries({ queryKey: ['tag-usage'] })
  }

  const create = useMutation({
    mutationFn: () => api.post<Tag>('/tags', { name: name.trim(), color, category }),
    onSuccess: () => {
      setName('')
      setError(null)
      invalidate()
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : 'Could not create the tag'),
  })

  const update = useMutation({
    mutationFn: (tag: Tag) =>
      api.patch<Tag>(`/tags/${tag.id}`, {
        name: tag.name,
        color: tag.color,
        category: tag.category,
        sort_order: tag.sort_order,
      }),
    onSuccess: invalidate,
  })

  const remove = useMutation({
    mutationFn: (id: number) => api.delete(`/tags/${id}`),
    onSuccess: () => {
      invalidate()
      void queryClient.invalidateQueries({ queryKey: ['trades'] })
    },
  })

  return (
    <Card>
      <CardHeader
        title="Tags"
        hint="Tag every trade honestly and the Reports page will tell you exactly what each habit costs."
      />

      <div className="mb-5 flex flex-wrap items-end gap-2 rounded-lg bg-[var(--tz-surface-2)] p-3">
        <Field label="New tag" className="min-w-40 flex-1">
          <input
            className="tz-input"
            placeholder="Chased the entry"
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && name.trim()) create.mutate()
            }}
          />
        </Field>
        <Field label="Category">
          <select
            className="tz-input"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          >
            {TAG_CATEGORIES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Colour">
          <input
            type="color"
            className="tz-input h-9 w-14 p-1"
            value={color}
            onChange={(event) => setColor(event.target.value)}
          />
        </Field>
        <Button
          variant="primary"
          disabled={!name.trim()}
          loading={create.isPending}
          onClick={() => create.mutate()}
        >
          Add
        </Button>
      </div>

      {error && <p className="mb-3 text-sm text-[var(--tz-loss-text)]">{error}</p>}

      {isLoading ? (
        <Skeleton className="h-40" />
      ) : (
        <div className="space-y-1">
          {tags.map((tag) => (
            <div
              key={tag.id}
              className="flex items-center gap-2 rounded-lg px-2 py-1.5 transition-colors hover:bg-[var(--tz-surface-hover)]"
            >
              <input
                type="color"
                className="size-6 shrink-0 cursor-pointer rounded border-0 bg-transparent p-0"
                value={tag.color}
                onChange={(event) => update.mutate({ ...tag, color: event.target.value })}
              />
              <input
                className="min-w-0 flex-1 border-0 bg-transparent text-sm outline-none"
                defaultValue={tag.name}
                onBlur={(event) => {
                  if (event.target.value.trim() && event.target.value !== tag.name) {
                    update.mutate({ ...tag, name: event.target.value.trim() })
                  }
                }}
              />
              <select
                className="border-0 bg-transparent text-xs text-[var(--tz-text-muted)] outline-none"
                value={tag.category}
                onChange={(event) =>
                  update.mutate({ ...tag, category: event.target.value as Tag['category'] })
                }
              >
                {TAG_CATEGORIES.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <span className="tabular w-14 shrink-0 text-right text-xs text-[var(--tz-text-faint)]">
                {usage[tag.name] ?? 0} used
              </span>
              <button
                type="button"
                aria-label={`Delete ${tag.name}`}
                className="shrink-0 text-[var(--tz-text-faint)] transition-colors hover:text-[var(--tz-loss-text)]"
                onClick={() => {
                  if (confirm(`Delete the tag "${tag.name}"? It will be removed from all trades.`))
                    remove.mutate(tag.id)
                }}
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

/* --------------------------------------------------------------------- */

function AccountSection() {
  const queryClient = useQueryClient()
  const { currency } = useSettings()
  const { data: accounts = [], isLoading } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => api.get<Account[]>('/accounts'),
  })

  const update = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Partial<Account> }) =>
      api.patch<Account>(`/accounts/${id}`, patch),
    onSuccess: () => void queryClient.invalidateQueries(),
  })

  if (isLoading) return <Skeleton className="h-48" />

  return (
    <div className="space-y-4">
      {accounts.map((account) => (
        <Card key={account.id}>
          <CardHeader
            title={account.name || `Account ${account.login}`}
            action={
              account.is_default ? (
                <span className="tz-chip bg-zulu-500/15 text-zulu-400">Default</span>
              ) : (
                <Button onClick={() => update.mutate({ id: account.id, patch: { is_default: true } })}>
                  Make default
                </Button>
              )
            }
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Display name">
              <input
                className="tz-input"
                defaultValue={account.name}
                onBlur={(event) =>
                  update.mutate({ id: account.id, patch: { name: event.target.value } })
                }
              />
            </Field>
            <Field
              label={`Starting balance (${currency})`}
              hint="The deposit this account began with. Drawdown percentages and percentage risk are measured against it."
            >
              <NumberField
                value={account.initial_balance}
                step={100}
                onCommit={(value) =>
                  update.mutate({ id: account.id, patch: { initial_balance: value } })
                }
              />
            </Field>
          </div>
          <dl className="mt-4 space-y-1.5 border-t border-[var(--tz-border)] pt-3 text-sm">
            <Fact inline label="Login" value={account.login} />
            <Fact inline label="Broker" value={account.broker || '—'} />
            <Fact inline label="Server" value={account.server || '—'} />
            <Fact inline label="Currency" value={account.currency} />
            <Fact inline label="Leverage" value={account.leverage ? `1:${account.leverage}` : '—'} />
            <Fact inline label="Balance" value={num(account.balance, 2)} />
          </dl>
        </Card>
      ))}
    </div>
  )
}

/* --------------------------------------------------------------------- */

function SecuritySection() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  const change = useMutation({
    mutationFn: () =>
      api.post('/auth/password', { current_password: current, new_password: next }),
    onSuccess: () => {
      setCurrent('')
      setNext('')
      setConfirmation('')
      setMessage({ kind: 'ok', text: 'Password changed. Other sessions were signed out.' })
    },
    onError: (error) =>
      setMessage({
        kind: 'error',
        text: error instanceof ApiError ? error.message : 'Could not change the password',
      }),
  })

  const valid = current && next.length >= 8 && next === confirmation

  return (
    <Card>
      <CardHeader
        title="Change password"
        hint="Changing the password signs out every other browser immediately."
      />
      <div className="grid max-w-md gap-4">
        <Field label="Current password">
          <input
            type="password"
            className="tz-input"
            autoComplete="current-password"
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
        </Field>
        <Field label="New password" hint="At least 8 characters.">
          <input
            type="password"
            className="tz-input"
            autoComplete="new-password"
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
        </Field>
        <Field label="Repeat the new password">
          <input
            type="password"
            className="tz-input"
            autoComplete="new-password"
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
          />
        </Field>
        {next && confirmation && next !== confirmation && (
          <p className="text-sm text-[var(--tz-loss-text)]">The two passwords do not match.</p>
        )}
        {message && (
          <p
            className={clsx(
              'text-sm',
              message.kind === 'ok' ? 'text-[var(--tz-gain-text)]' : 'text-[var(--tz-loss-text)]',
            )}
          >
            {message.text}
          </p>
        )}
        <Button
          variant="primary"
          disabled={!valid}
          loading={change.isPending}
          onClick={() => change.mutate()}
        >
          Change password
        </Button>
      </div>
    </Card>
  )
}

/* --------------------------------------------------------------------- */

function NumberField({
  value,
  step,
  disabled,
  onCommit,
}: {
  value: number
  step: number
  disabled?: boolean
  onCommit: (value: number) => void
}) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => setDraft(String(value)), [value])

  return (
    <input
      type="number"
      step={step}
      disabled={disabled}
      className="tz-input disabled:opacity-50"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => {
        const parsed = Number(draft)
        if (Number.isFinite(parsed) && parsed !== value) onCommit(parsed)
        else setDraft(String(value))
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter') event.currentTarget.blur()
      }}
    />
  )
}
