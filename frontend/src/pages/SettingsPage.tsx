import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import {
  AlertTriangle,
  Check,
  Copy,
  Database,
  Download,
  Gauge,
  CandlestickChart,
  Palette,
  RefreshCw,
  Shield,
  SlidersHorizontal,
  Tags as TagsIcon,
  Trash2,
} from 'lucide-react'
import clsx from 'clsx'
import { ApiError, api } from '../lib/api'
import { useSettings, useTagCategories } from '../lib/settings'
import type { DeepPartial } from '../lib/settings'
import { PERIOD_OPTIONS } from '../lib/period'
import type { Account, AppSettings, SystemInfo, Tag } from '../lib/types'
import { Button, Card, CardHeader, Field, SegmentedControl, Skeleton, Toggle } from '../components/ui'
import { AccountsPage } from './AccountsPage'

// Accounts live here, with the rest of what is configured once and left alone.
// They had a page of their own for a while; a top-level menu item for
// something visited when an account is added, and never again, was a page's
// worth of chrome for a settings screen.
const SECTIONS = [
  { id: 'general', label: 'General', icon: Palette },
  { id: 'accounts', label: 'Accounts', icon: Copy },
  { id: 'risk', label: 'Risk & R', icon: SlidersHorizontal },
  { id: 'score', label: 'Zulu Score', icon: Gauge },
  { id: 'charts', label: 'Charts', icon: CandlestickChart },
  { id: 'tags', label: 'Tags', icon: TagsIcon },
  { id: 'data', label: 'Data', icon: Database },
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

  // Links such as /settings#data must land on the right section even when the
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
        {section === 'accounts' && <AccountsPage />}
        {section === 'risk' && <RiskSection />}
        {section === 'score' && <ScoreSection />}
        {section === 'charts' && <ChartsSection />}
        {section === 'tags' && <TagsSection />}
        {section === 'data' && <DataSection />}
        {section === 'security' && <SecuritySection />}
      </div>
    </div>
  )
}

/* --------------------------------------------------------------------- */

/** Exporting the journal.
 *
 *  Its own card rather than a button on the import one: they are opposite
 *  errands, and the export is the one people come looking for. One format --
 *  CSV opens everywhere and needs nothing installed -- and every account by
 *  default, since a file missing half the journal is worse than no file.
 */
function ExportCard() {
  const [scope, setScope] = useState('all')
  const [busy, setBusy] = useState(false)
  const { data: accounts = [] } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => api.get<Account[]>('/accounts'),
  })

  const download = async () => {
    setBusy(true)
    try {
      const query: Record<string, string> = { period: 'all' }
      if (scope !== 'all') query.account_id = scope
      const who = scope === 'all' ? 'all-accounts' : scope
      await api.download('/trades/export.csv', query, `tradezulu-${who}-trades.csv`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <CardHeader
        title="Export trades"
        hint="Every closed trade as CSV: account, symbol, direction, times, prices, stop and target, costs, net P&L, R, outcome, setup, rating, tags and notes."
      />
      <p className="mb-3 text-sm text-[var(--tz-text-muted)]">
        One row per trade, all of history. Opens in any spreadsheet, and reads back into TradeZulu.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Which account">
          <select
            className="tz-input min-w-[14rem]"
            value={scope}
            onChange={(event) => setScope(event.target.value)}
          >
            <option value="all">All accounts</option>
            {accounts.map((account) => (
              <option key={account.id} value={String(account.id)}>
                {account.name || account.login}
              </option>
            ))}
          </select>
        </Field>
        <Button variant="primary" icon={<Download size={15} />} loading={busy} onClick={download}>
          Download CSV
        </Button>
      </div>
    </Card>
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

//: Every currency ForexFactory files a release under. "All" is theirs for
//: events that belong to none, and is never a choice -- those always show.
const FF_CURRENCIES = ['USD', 'EUR', 'GBP', 'JPY', 'CHF', 'CAD', 'AUD', 'NZD', 'CNY']

const FF_IMPACTS = [
  { value: 'High', label: 'Red' },
  { value: 'Medium', label: 'Orange' },
  { value: 'Low', label: 'Yellow' },
  { value: 'Holiday', label: 'Holidays' },
]

/** Pick any number of things, one tap each.
 *
 *  A dropdown of fixed combinations was the wrong shape: it could offer "red
 *  and orange" but not "red and holidays", which is a perfectly ordinary thing
 *  to want -- the releases that move price, and the days nothing will.
 */
function ChipPicker({
  options,
  selected,
  onChange,
}: {
  options: { value: string; label: string }[]
  selected: string[]
  onChange: (values: string[]) => void
}) {
  const toggle = (value: string) => {
    const next = selected.includes(value)
      ? selected.filter((entry) => entry !== value)
      : [...selected, value]
    // Kept in the order they are offered, so the saved list reads the same way
    // every time rather than in the order they happened to be clicked.
    onChange(options.filter((option) => next.includes(option.value)).map((o) => o.value))
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((option) => {
        const on = selected.includes(option.value)
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => toggle(option.value)}
            aria-pressed={on}
            className={clsx(
              'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
              on
                ? 'border-zulu-500/50 bg-zulu-500/15 text-zulu-400'
                : 'border-[var(--tz-border)] text-[var(--tz-text-muted)] hover:text-[var(--tz-text)]',
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
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
  const { data: system } = useQuery({
    queryKey: ['system'],
    queryFn: () => api.get<SystemInfo>('/settings/system'),
    staleTime: Infinity,
  })

  return (
    <div className="space-y-4">
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

      <div className="mt-4 grid gap-4 border-t border-[var(--tz-border)] pt-4 sm:grid-cols-2">
        <Field
          label="Economic calendar"
          hint="TradingView's widget brings its own data and its own look. ForexFactory publishes a feed, which this server reads and draws — it is the one people quote folder colours from."
        >
          <SegmentedControl
            value={settings.news?.provider ?? 'forexfactory'}
            onChange={(value) => void apply({ news: { provider: value } })}
            options={[
              { value: 'forexfactory', label: 'ForexFactory' },
              { value: 'tradingview', label: 'TradingView' },
            ]}
          />
        </Field>
      </div>

      {(settings.news?.provider ?? 'forexfactory') === 'forexfactory' ? (
        <div className="mt-4 space-y-4">
          <Field
            label="ForexFactory: currencies"
            hint="Pick as many as you follow. Releases ForexFactory marks “All”, such as OPEC meetings, are always shown — they belong to no currency and move everything."
          >
            <ChipPicker
              options={FF_CURRENCIES.map((code) => ({ value: code, label: code }))}
              selected={settings.news?.currencies ?? ['USD']}
              onChange={(currencies) => void apply({ news: { currencies } })}
            />
          </Field>
          <Field
            label="ForexFactory: folders"
            hint="Red is high impact. Any combination works — red and holidays alone is a perfectly reasonable filter."
          >
            <ChipPicker
              options={FF_IMPACTS}
              selected={settings.news?.impacts ?? ['High']}
              onChange={(impacts) => void apply({ news: { impacts } })}
            />
          </Field>
        </div>
      ) : (
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field
          label="Economic calendar: countries"
          hint="Comma-separated country codes — us, eu, gb, jp. The dollar alone is the default, since that is what moves most instruments."
        >
          <input
            className="tz-input"
            defaultValue={(settings.news?.countries ?? ['us']).join(', ')}
            onBlur={(event) =>
              void apply({
                news: {
                  countries: event.target.value
                    .split(/[\s,]+/)
                    .map((code) => code.trim().toLowerCase())
                    .filter(Boolean),
                },
              })
            }
          />
        </Field>
        <Field label="Economic calendar: impact">
          <select
            className="tz-input"
            value={String(settings.news?.importance ?? 1)}
            onChange={(event) =>
              void apply({ news: { importance: Number(event.target.value) } })
            }
          >
            <option value="1">High impact only</option>
            <option value="0">Medium and high</option>
            <option value="-1">Everything</option>
          </select>
        </Field>
      </div>
      )}

      <div className="mt-4 border-t border-[var(--tz-border)] pt-2">
        <Toggle
          label="Show money, not percentages"
          description="Off by default, so the dashboard can be screenshotted and shared without showing what the account is worth. Figures appear as a percentage of the balance the period opened with instead."
          checked={general.show_amounts}
          onChange={(value) => void apply({ general: { show_amounts: value } })}
        />
        <Toggle
          label="Colour-blind friendly results"
          description="Uses blue for profit and amber for loss instead of green and red. Both pairs stay distinguishable with any form of colour blindness."
          checked={general.colorblind_mode}
          onChange={(value) => void apply({ general: { colorblind_mode: value } })}
        />
      </div>
    </Card>

    {/* None of this is about MetaTrader, which is where it used to sit. It
        describes the installation, so it belongs where someone would look for
        it when asked what version they are running. */}
    {system && (
      <Card>
        <CardHeader title="About this installation" />
        <dl className="space-y-1.5 text-sm">
          <Fact inline label="Version" value={system.version} />
          <Fact inline label="Data directory" value={system.data_dir} />
          <Fact inline label="Trades stored" value={String(system.trades)} />
          {system.secret_key_ephemeral && (
            <p className="flex items-center gap-1.5 pt-1 text-[var(--tz-loss-text)]">
              <AlertTriangle size={14} /> TZ_SECRET_KEY is unset — you will be logged out on
              every restart.
            </p>
          )}
        </dl>
      </Card>
    )}
    </div>
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

        {/* Said here rather than only in the tooltips: three boxes that look
            like a form to fill in are really three spellings of one idea, and
            nothing about them suggests that zero is a valid answer. */}
        <p className="mb-4 text-sm text-[var(--tz-text-muted)]">
          Three ways of saying how little counts as nothing — in R, in {currency}, or as a share
          of the account. They are <strong>alternatives, not conditions</strong>: any one of them
          calling a trade a breakeven is enough. Set a threshold to{' '}
          <strong className="text-[var(--tz-text)]">0</strong> to switch that one off, and set all
          three to 0 to stop marking breakevens at all.
        </p>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Breakeven threshold (R)"
            hint="Any closed trade whose realised R is smaller than this, in either direction, is a breakeven. 0 switches it off."
          >
            <NumberField
              value={risk.breakeven_threshold_r}
              step={0.01}
              onCommit={(value) => void apply({ risk: { breakeven_threshold_r: value } })}
              off={!risk.breakeven_threshold_r}
            />
          </Field>
          <Field
            label={`Breakeven threshold (${currency})`}
            hint="Used only when a trade has no known risk, so no R can be computed. 0 switches it off."
          >
            <NumberField
              value={risk.breakeven_threshold_money}
              step={0.5}
              onCommit={(value) => void apply({ risk: { breakeven_threshold_money: value } })}
              off={!risk.breakeven_threshold_money}
            />
          </Field>
          <Field
            label="Breakeven threshold (% of account)"
            hint="For people who think in percent. Applies whether or not the trade had a stop, since it measures the account rather than the risk. 0 switches it off."
          >
            <NumberField
              value={risk.breakeven_threshold_percent}
              step={0.05}
              onCommit={(value) => void apply({ risk: { breakeven_threshold_percent: value } })}
              off={!risk.breakeven_threshold_percent}
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
          title="Costs and R"
          hint="R is money risked. It comes from the stop MetaTrader recorded on the entry order; a trade opened without one has an R only if it lost, because the loss is what it turned out to be risking."
        />
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

// The weight and the target are different keys for two of these: a component
// is named for what it measures, its target for the number it is measured
// against. Sharing one key meant the "Even losses" weight was written to
// weights.worst_loss_multiple, which nothing reads and the settings document
// drops on save — so that control appeared to work and changed nothing.
const SCORE_COMPONENTS = [
  { key: 'win_rate', target: 'win_rate', label: 'Win rate', unit: '%', hint: 'Win rate that scores 100.' },
  { key: 'profit_factor', target: 'profit_factor', label: 'Profit factor', unit: '', hint: 'Profit factor that scores 100.' },
  { key: 'avg_win_loss', target: 'avg_win_loss', label: 'Avg win / loss', unit: '', hint: 'Payoff ratio that scores 100.' },
  {
    key: 'max_drawdown',
    target: 'max_drawdown_pct',
    label: 'Drawdown',
    unit: '%',
    hint: 'How far below its high-water mark the account may fall before this scores 0. Measured from the peak, like the drawdown on the reports page.',
  },
  {
    key: 'loss_consistency',
    target: 'worst_loss_multiple',
    label: 'Even losses',
    unit: '×',
    hint:
      'Your worst loss measured against a typical one — the median of every loss in the period. ' +
      'Losses all sized the same score 100; the target is the multiple at which the score reaches ' +
      '0, so at 3 a worst loss three times a typical one scores nothing and 2× scores half marks. ' +
      'It needs at least three losses before a typical one exists, and is blank until then. Off by ' +
      'default because it answers a different question from Drawdown: not how far the account fell, ' +
      'but whether you sized every loser the same way.',
  },
  { key: 'recovery_factor', target: 'recovery_factor', label: 'Recovery factor', unit: '', hint: 'Recovery factor that scores 100.' },
  { key: 'consistency', target: 'consistency', label: 'Consistency', unit: '%', hint: 'Consistency that scores 100.' },
] as const

function ScoreSection() {
  const { settings } = useSettings()
  const { apply, saved } = useSaver()
  const score = settings.zulu_score

  return (
    <Card>
      <CardHeader
        title="Zulu Score"
        hint="Each component you switch on is scored 0-100 against its target, then averaged using the weights. Switch them all off and there is no score, rather than a score of zero."
        action={<SavedFlag saved={saved} />}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--tz-border)] text-left text-xs text-[var(--tz-text-muted)]">
              <th className="py-2 font-medium">Use</th>
              <th className="py-2 font-medium">Component</th>
              <th className="py-2 font-medium">Target</th>
              <th className="py-2 font-medium">Weight</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--tz-border)]">
            {SCORE_COMPONENTS.map((component) => {
              const weight = score.weights[component.key] ?? 0
              const on = weight > 0
              return (
                <tr key={component.key} className={on ? undefined : 'opacity-60'}>
                  <td className="w-10 py-2 align-top">
                    <input
                      type="checkbox"
                      className="mt-1 size-4 accent-[var(--tz-accent)]"
                      checked={on}
                      aria-label={`Use ${component.label}`}
                      onChange={(event) =>
                        void apply({
                          zulu_score: {
                            // Back to an equal say, not to whatever it was:
                            // a weight that was tuned and then switched off is
                            // a decision the number no longer records.
                            weights: { [component.key]: event.target.checked ? 1 : 0 },
                          },
                        })
                      }
                    />
                  </td>
                  <td className="py-2 pr-3">
                    <span className="font-medium">{component.label}</span>
                    <span className="mt-0.5 block text-xs text-[var(--tz-text-muted)]">
                      {component.hint}
                    </span>
                  </td>
                  <td className="w-28 py-2 pr-3 align-top">
                    <div className="flex items-center gap-1">
                      <NumberField
                        value={score.targets[component.target] ?? 0}
                        step={component.unit === '%' ? 1 : 0.1}
                        onCommit={(value) =>
                          void apply({ zulu_score: { targets: { [component.target]: value } } })
                        }
                      />
                      {component.unit && (
                        <span className="text-xs text-[var(--tz-text-muted)]">
                          {component.unit}
                        </span>
                      )}
                    </div>
                  </td>
                  <td className="w-24 py-2 align-top">
                    <NumberField
                      value={weight}
                      step={0.5}
                      disabled={!on}
                      onCommit={(value) =>
                        void apply({ zulu_score: { weights: { [component.key]: value } } })
                      }
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

/* --------------------------------------------------------------------- */

function DataSection() {
  const queryClient = useQueryClient()

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
      <ExportCard />

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
      </Card>
    </div>
  )
}

/* --------------------------------------------------------------------- */

function ChartsSection() {
  const { settings } = useSettings()
  const { apply } = useSaver()
  return (
    <div className="space-y-4">
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
            hint="Worked out from your broker automatically — Vantage charts resolve as VANTAGE:. Set this only to override that, for a feed the list does not know."
            className="sm:col-span-2"
          >
            <input
              className="tz-input"
              placeholder="automatic"
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
/** Editing the groups tags are filed under.
 *
 *  The value is what gets stored on a tag, so renaming a group's label is safe
 *  while changing its value orphans the tags pointing at the old one -- they
 *  fall back to "Other" rather than disappearing.
 */
function TagCategoriesCard() {
  const { settings, save } = useSettings()
  const configured = settings.tags?.categories ?? []
  const [draft, setDraft] = useState('')

  const update = (next: { value: string; label: string }[]) =>
    void save({ tags: { categories: next } })

  return (
    <Card>
      <CardHeader
        title="Tag groups"
        hint="How the tag list is organised. Setup, Mistake and Behaviour are only defaults; anything filed under a group you remove shows up under Other."
      />
      <div className="space-y-2">
        {configured.map((category, index) => (
          <div key={category.value} className="flex items-center gap-2">
            <input
              className="tz-input flex-1"
              defaultValue={category.label}
              onBlur={(event) => {
                const label = event.target.value.trim()
                if (!label || label === category.label) return
                const next = [...configured]
                next[index] = { ...category, label }
                update(next)
              }}
            />
            <code className="w-28 shrink-0 truncate text-xs text-[var(--tz-text-faint)]">
              {category.value}
            </code>
            <button
              type="button"
              aria-label={`Remove ${category.label}`}
              className="text-[var(--tz-text-faint)] hover:text-[var(--tz-loss-text)]"
              onClick={() => update(configured.filter((_, i) => i !== index))}
            >
              <Trash2 size={15} />
            </button>
          </div>
        ))}
      </div>

      <div className="mt-3 flex gap-2">
        <input
          className="tz-input flex-1"
          placeholder="Add a group, e.g. Session"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
        <Button
          onClick={() => {
            const label = draft.trim()
            if (!label) return
            // The stored value is derived once and then fixed: tags point at
            // it, so it must not move when the label is edited later.
            const value = label.toLowerCase().replace(/[^a-z0-9]+/g, '_').slice(0, 24)
            if (!value || configured.some((c) => c.value === value)) return
            update([...configured, { value, label }])
            setDraft('')
          }}
        >
          Add
        </Button>
      </div>
    </Card>
  )
}

function TagsSection() {
  const TAG_CATEGORIES = useTagCategories()
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
    <div className="space-y-4">
      <TagCategoriesCard />

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
  off,
  onCommit,
}: {
  value: number
  step: number
  disabled?: boolean
  /** Mark a zero as "switched off" rather than as a box nobody filled in. */
  off?: boolean
  onCommit: (value: number) => void
}) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => setDraft(String(value)), [value])

  const input = (
    <input
      type="number"
      step={step}
      disabled={disabled}
      className={clsx('tz-input disabled:opacity-50', off && 'pr-10')}
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

  if (!off) return input
  return (
    <div className="relative">
      {input}
      <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-[var(--tz-text-faint)]">
        off
      </span>
    </div>
  )
}
