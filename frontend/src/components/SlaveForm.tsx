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

const SIZING_MODES = [
  { value: 'balance_ratio', label: 'Match the balance ratio', hint: 'A slave half the size trades half the lots.' },
  { value: 'equity_ratio', label: 'Match the equity ratio', hint: 'As above, but on equity rather than balance.' },
  { value: 'multiplier', label: "Multiply the master's lots", hint: 'Ignores account sizes entirely.' },
  { value: 'fixed_lot', label: 'Always the same lot size', hint: 'Whatever the master traded.' },
  { value: 'risk_percent', label: 'Risk a percentage of equity', hint: "Sized against the master's stop distance." },
]

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
  scale: 1,
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
              <Field label="Account number">
                <input
                  className="tz-input"
                  value={login}
                  onChange={(event) => setLogin(event.target.value)}
                  placeholder="5000123"
                />
              </Field>
              <Field label="Trade server">
                <input
                  className="tz-input"
                  value={server}
                  onChange={(event) => setServer(event.target.value)}
                  placeholder="ICMarketsSC-Live12"
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
              <Field label="Broker" hint="Optional, for your own reference.">
                <input
                  className="tz-input"
                  value={broker}
                  onChange={(event) => setBroker(event.target.value)}
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
              <div className="grid grid-cols-2 gap-3">
                <Field label="Symbol prefix" hint="e.g. FX_">
                  <input
                    className="tz-input"
                    value={prefix}
                    onChange={(event) => setPrefix(event.target.value)}
                  />
                </Field>
                <Field label="Symbol suffix" hint="e.g. .r">
                  <input
                    className="tz-input"
                    value={suffix}
                    onChange={(event) => setSuffix(event.target.value)}
                  />
                </Field>
              </div>
            </div>
          </section>

          <section>
            <h3 className="tz-label">How big should each copy be?</h3>
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
                {settings.mode === 'risk_percent' && (
                  <Num label="Risk per trade (%)" value={settings.risk_percent} onChange={(v) => set('risk_percent', v)} step={0.1} />
                )}
                <Num label="Never exceed (lots)" value={settings.max_lot} onChange={(v) => set('max_lot', v)} step={0.01} zero="no cap" />
                <Num label="Extra scaling" value={settings.scale} onChange={(v) => set('scale', v)} step={0.05} />
              </div>

              <Toggle
                checked={settings.mirror_stops}
                onChange={(value) => set('mirror_stops', value)}
                label="Follow the master's stop and target changes"
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
                label="Skip any master trade that has no stop loss"
              />
            </div>
          </section>

          <section>
            <h3 className="tz-label">Stop the account when…</h3>
            <div className="grid gap-3 sm:grid-cols-3">
              <Num label="Down today (%)" value={settings.max_daily_drawdown_percent} onChange={(v) => set('max_daily_drawdown_percent', v)} step={0.5} zero="no limit" />
              <Num label="Below peak (%)" value={settings.equity_stop_percent} onChange={(v) => set('equity_stop_percent', v)} step={0.5} zero="no limit" />
              <Num label="Equity floor" value={settings.equity_stop_amount} onChange={(v) => set('equity_stop_amount', v)} step={100} zero="none" />
            </div>
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
            <h3 className="tz-label">Prop firm rules</h3>
            <div className="grid gap-3 sm:grid-cols-4">
              <Num label="Bank a winner at" value={settings.take_profit_at_amount} onChange={(v) => set('take_profit_at_amount', v)} step={50} zero="off" />
              <Num label="…or at (R)" value={settings.take_profit_at_r} onChange={(v) => set('take_profit_at_r', v)} step={0.5} zero="off" />
              <Num label="Daily target (%)" value={settings.daily_profit_target_percent} onChange={(v) => set('daily_profit_target_percent', v)} step={0.5} zero="off" />
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
