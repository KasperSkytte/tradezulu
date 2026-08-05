/**
 * Adding or editing a slave account.
 *
 * The rules are grouped the way you think about them rather than the way they
 * are stored: how big should the trade be, what will I not allow on a single
 * trade, and what stops the whole account. Every limit accepts 0 for "no
 * limit", so the form never forces a number on someone who does not want one.
 */

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Loader2, X } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import type { CopySettings, SlaveAccount } from '../lib/types'
import { Button, Field, Toggle } from './ui'
import { BrokerServerPicker } from './BrokerServerPicker'

const SIZING_MODES = [
  { value: 'balance_ratio', label: 'Match the balance ratio', hint: 'A slave half the size trades half the lots.' },
  { value: 'equity_ratio', label: 'Match the equity ratio', hint: 'As above, but on equity rather than balance.' },
  { value: 'multiplier', label: "Multiply the master's lots", hint: 'Ignores account sizes entirely.' },
  { value: 'fixed_lot', label: 'Always the same lot size', hint: 'Whatever the master traded.' },
  {
    value: 'risk_percent_balance',
    label: 'Risk a percentage of balance',
    hint: "Sized against the master's stop distance. Balance ignores open trades, so the amount risked stays the same while a position is running.",
  },
  {
    value: 'risk_percent',
    label: 'Risk a percentage of equity',
    hint: "Sized against the master's stop distance. Equity moves with open trades, so a losing position shrinks the next trade.",
  },
]

const RISK_MODES = new Set(['risk_percent', 'risk_percent_balance'])

const BREACH_ACTIONS = [
  { value: 'close_all', label: 'Close everything and stop' },
  { value: 'stop_opening', label: 'Stop opening, keep managing' },
  { value: 'flatten_on_equity_stop', label: 'Flatten only on the equity stop' },
]

const EMPTY: CopySettings = {
  mode: 'balance_ratio',
  multiplier: 1,
  fixed_lot: 0.01,
  risk_percent: 1,
  max_lot: 0,
  min_lot: 0,
  mirror_stops: true,
  max_risk_percent_per_trade: 2,
  max_lot_per_trade: 0,
  require_stop_loss: false,
  max_open_positions: 0,
  max_same_direction: 0,
  max_positions_per_symbol: 0,
  max_total_lots: 0,
  max_daily_drawdown_percent: 0,
  equity_stop_percent: 0,
  equity_stop_amount: 0,
  breach_action: 'close_all',
  take_profit_at_amount: 0,
  take_profit_at_r: 0,
  daily_profit_target_percent: 0,
  max_day_share_of_profit_percent: 0,
  allowed_symbols: [],
  blocked_symbols: [],
}

export function SlaveForm({
  account,
  onClose,
  onSaved,
}: {
  account: SlaveAccount | null
  onClose: () => void
  onSaved: () => void
}) {
  const editing = account !== null
  const [login, setLogin] = useState(account?.login ?? '')
  const [server, setServer] = useState(account?.server ?? '')
  const [name, setName] = useState(account?.name ?? '')
  const [broker, setBroker] = useState(account?.broker ?? '')
  const [password, setPassword] = useState('')
  const [prefix, setPrefix] = useState(account?.symbol_prefix ?? '')
  const [suffix, setSuffix] = useState(account?.symbol_suffix ?? '')
  const [settings, setSettings] = useState<CopySettings>({ ...EMPTY, ...(account?.settings ?? {}) })
  const [error, setError] = useState<string | null>(null)

  const set = <K extends keyof CopySettings>(key: K, value: CopySettings[K]) =>
    setSettings((current) => ({ ...current, [key]: value }))

  const save = useMutation({
    mutationFn: () => {
      const body = {
        login,
        server,
        name,
        broker,
        symbol_prefix: prefix,
        symbol_suffix: suffix,
        symbol_map: account?.symbol_map ?? {},
        settings,
        // Sending undefined keeps whatever is stored.
        ...(password ? { password } : {}),
      }
      return editing
        ? api.put(`/accounts/${account.id}`, body)
        : api.post('/accounts', body)
    },
    onSuccess: onSaved,
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : 'Could not save that'),
  })

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/50 p-4 sm:p-8"
      onClick={onClose}
    >
      <div
        className="tz-card w-full max-w-3xl p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">
              {editing ? `${account.name}` : 'Add a slave account'}
            </h2>
            <p className="mt-1 text-sm text-[var(--tz-text-muted)]">
              {editing
                ? 'Changes take effect on the next copy. Arming is separate.'
                : 'It starts switched off. You arm it once you have looked at what it would do.'}
            </p>
          </div>
          <button onClick={onClose} className="text-[var(--tz-text-faint)] hover:text-[var(--tz-text)]">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-6">
          <section>
            <h3 className="tz-label">The account</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <BrokerServerPicker
                server={server}
                onChange={({ server: next, broker: named }) => {
                  setServer(next)
                  // Only fill the broker in; never blank one the terminal has
                  // already reported, and never overwrite something typed.
                  if (named) setBroker(named)
                }}
              />
              <Field label="Account number">
                <input
                  className="tz-input"
                  value={login}
                  onChange={(event) => setLogin(event.target.value)}
                  placeholder="5000123"
                />
              </Field>
              <Field label="Name" hint="What you want to call it here.">
                <input
                  className="tz-input"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Prop challenge #1"
                />
              </Field>
              <Field
                label={editing ? 'Password (leave blank to keep)' : 'Password'}
                hint="The trade-enabled password, not the investor one — an investor password cannot place orders."
              >
                <input
                  type="password"
                  className="tz-input"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete="new-password"
                />
              </Field>
            </div>
            {/* Symbol naming used to be two text boxes here. Nobody should have
                to know their broker writes EURUSD as EURUSD+ -- the symbol list
                the terminal reports says so, and it is read off that. Anything
                set by hand earlier still wins, so an existing account keeps
                working. */}
            <p className="mt-3 text-xs text-[var(--tz-text-faint)]">
              {prefix || suffix ? (
                <>
                  Symbol naming is set by hand for this account:{' '}
                  <code>
                    {prefix}EURUSD{suffix}
                  </code>
                  .{' '}
                  <button
                    type="button"
                    className="underline hover:text-[var(--tz-text)]"
                    onClick={() => {
                      setPrefix('')
                      setSuffix('')
                    }}
                  >
                    Detect it instead
                  </button>
                </>
              ) : (
                "The broker's symbol naming — a EURUSD+ or an FX_EURUSD — is worked out from the symbol list the terminal reports."
              )}
            </p>
          </section>

          <section>
            <h3 className="tz-label">Position sizing</h3>
            <div className="space-y-3">
              <select
                className="tz-input"
                value={settings.mode}
                onChange={(event) => set('mode', event.target.value)}
              >
                {SIZING_MODES.map((mode) => (
                  <option key={mode.value} value={mode.value}>
                    {mode.label}
                  </option>
                ))}
              </select>
              <p className="text-xs text-[var(--tz-text-faint)]">
                {SIZING_MODES.find((mode) => mode.value === settings.mode)?.hint}
              </p>

              <div className="grid gap-3 sm:grid-cols-3">
                {settings.mode === 'multiplier' && (
                  <Num label="Multiplier" value={settings.multiplier} onChange={(v) => set('multiplier', v)} step={0.1} />
                )}
                {settings.mode === 'fixed_lot' && (
                  <Num label="Lots" value={settings.fixed_lot} onChange={(v) => set('fixed_lot', v)} step={0.01} />
                )}
                {RISK_MODES.has(settings.mode) && (
                  <Num label="Risk per trade (%)" value={settings.risk_percent} onChange={(v) => set('risk_percent', v)} step={0.1} />
                )}
                <Num
                  label="Max position size (lots)"
                  value={settings.max_lot}
                  onChange={(v) => set('max_lot', v)}
                  step={0.01}
                  zero="no cap"
                />
                {/* Sizing rounds down and never up, so a slave a hair smaller
                    than the master computes 0.00998 lots and refuses the trade
                    outright. This is the way out, and it was previously stored
                    but never shown. */}
                <Num
                  label="Min position size (lots)"
                  value={settings.min_lot}
                  onChange={(v) => set('min_lot', v)}
                  step={0.01}
                  zero="the broker's own minimum"
                />
              </div>

              <Toggle
                checked={settings.mirror_stops}
                onChange={(value) => set('mirror_stops', value)}
                label="Follow the master's stop and target changes"
                description="Move the copy's stop and target whenever the master moves its own."
              />
            </div>
          </section>

          <section>
            <h3 className="tz-label">Refuse a trade when…</h3>
            <div className="grid gap-3 sm:grid-cols-3">
              <Num label="Risk over (% equity)" value={settings.max_risk_percent_per_trade} onChange={(v) => set('max_risk_percent_per_trade', v)} step={0.1} zero="no limit" />
              <Num label="Size over (lots)" value={settings.max_lot_per_trade} onChange={(v) => set('max_lot_per_trade', v)} step={0.01} zero="no limit" />
              <Num label="Open positions at" value={settings.max_open_positions} onChange={(v) => set('max_open_positions', v)} step={1} zero="no limit" />
              <Num label="Same direction at" value={settings.max_same_direction} onChange={(v) => set('max_same_direction', v)} step={1} zero="no limit" />
              <Num label="Per symbol at" value={settings.max_positions_per_symbol} onChange={(v) => set('max_positions_per_symbol', v)} step={1} zero="no limit" />
              <Num label="Total exposure (lots)" value={settings.max_total_lots} onChange={(v) => set('max_total_lots', v)} step={0.1} zero="no limit" />
            </div>
            <div className="mt-3">
              <Toggle
                checked={settings.require_stop_loss}
                onChange={(value) => set('require_stop_loss', value)}
                label="Require a stop loss"
                description="Skip any master trade that has none, rather than copying it naked."
              />
            </div>
          </section>

          <section>
            <h3 className="tz-label">Which instruments</h3>
            <div className="grid gap-3 sm:grid-cols-2">
              <SymbolList
                label="Only these"
                hint="Leave empty to copy everything the master trades."
                value={settings.allowed_symbols}
                onChange={(value) => set('allowed_symbols', value)}
              />
              <SymbolList
                label="Never these"
                hint="Checked after the list above."
                value={settings.blocked_symbols}
                onChange={(value) => set('blocked_symbols', value)}
              />
            </div>
            <p className="mt-2 text-xs text-[var(--tz-text-faint)]">
              Base names, separated by spaces or commas — the broker's own prefix and suffix are
              worked out for you, so <code>EURUSD</code> matches <code>EURUSD+</code> too.
            </p>
          </section>

          <section>
            <h3 className="tz-label">Stop the account when…</h3>
            <div className="grid gap-3 sm:grid-cols-4">
              <Num label="Down today (%)" value={settings.max_daily_drawdown_percent} onChange={(v) => set('max_daily_drawdown_percent', v)} step={0.5} zero="no limit" />
              <Num label="Below peak (%)" value={settings.equity_stop_percent} onChange={(v) => set('equity_stop_percent', v)} step={0.5} zero="no limit" />
              <Num label="Equity falls to" value={settings.equity_stop_amount} onChange={(v) => set('equity_stop_amount', v)} step={100} zero="none" />
              <Num label="Up today (%)" value={settings.daily_profit_target_percent} onChange={(v) => set('daily_profit_target_percent', v)} step={0.5} zero="no target" />
            </div>
            <p className="mt-2 text-xs text-[var(--tz-text-faint)]">
              “Equity falls to” is an amount in account currency, not a loss —
              the account stops when equity reaches it. The daily figures are measured against
              what the account was worth when the day opened, and profit against what has actually
              been banked rather than what is still on the table.
            </p>
            <div className="mt-3">
              <Field label="When one of those trips">
                <select
                  className="tz-input"
                  value={settings.breach_action}
                  onChange={(event) => set('breach_action', event.target.value)}
                >
                  {BREACH_ACTIONS.map((action) => (
                    <option key={action.value} value={action.value}>
                      {action.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          </section>

          <section>
            <h3 className="tz-label">Take profit off the table</h3>
            <div className="grid gap-3 sm:grid-cols-3">
              <Num label="Bank a winner at" value={settings.take_profit_at_amount} onChange={(v) => set('take_profit_at_amount', v)} step={50} zero="off" />
              <Num label="…or at (R)" value={settings.take_profit_at_r} onChange={(v) => set('take_profit_at_r', v)} step={0.5} zero="off" />
              <Num label="One day max (% of profit)" value={settings.max_day_share_of_profit_percent} onChange={(v) => set('max_day_share_of_profit_percent', v)} step={5} zero="off" />
            </div>
            <p className="mt-2 text-xs text-[var(--tz-text-faint)]">
              A single outsized win is what usually breaks a consistency rule. Closing winners
              early caps that, and the last field blocks new trades once one day is carrying too
              much of the total.
            </p>
          </section>

          {error && (
            <p className="rounded-lg border border-loss-500/30 bg-loss-500/10 px-3 py-2 text-sm text-loss-400">
              {error}
            </p>
          )}

          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button onClick={() => save.mutate()} disabled={save.isPending}>
              {save.isPending && <Loader2 size={15} className="animate-spin" />}
              {editing ? 'Save' : 'Add it'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}

function SymbolList({
  label,
  hint,
  value,
  onChange,
}: {
  label: string
  hint?: string
  value: string[]
  onChange: (value: string[]) => void
}) {
  // Held as typed rather than as the parsed array, so a trailing space or a
  // half-written name does not disappear under the cursor between keystrokes.
  const [text, setText] = useState(value.join(' '))
  return (
    <Field label={label} hint={hint}>
      <input
        className="tz-input"
        value={text}
        placeholder="EURUSD GBPUSD"
        onChange={(event) => {
          setText(event.target.value)
          onChange(
            event.target.value
              .split(/[\s,]+/)
              .map((item) => item.trim().toUpperCase())
              .filter(Boolean),
          )
        }}
      />
    </Field>
  )
}

function Num({
  label,
  value,
  onChange,
  step = 1,
  zero,
}: {
  label: string
  value: number
  onChange: (value: number) => void
  step?: number
  zero?: string
}) {
  return (
    <Field label={label} hint={zero && value === 0 ? zero : undefined}>
      <input
        type="number"
        className="tz-input tabular"
        value={value}
        step={step}
        min={0}
        onChange={(event) => onChange(Number(event.target.value) || 0)}
      />
    </Field>
  )
}
