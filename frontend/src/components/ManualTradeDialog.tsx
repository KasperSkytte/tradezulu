import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, api } from '../lib/api'
import type { Trade } from '../lib/types'
import { Button, Field } from './ui'
import { Dialog } from './Dialog'

interface FormState {
  symbol: string
  direction: 'long' | 'short'
  opened_at: string
  closed_at: string
  volume: string
  entry_price: string
  exit_price: string
  initial_stop: string
  initial_target: string
  gross_profit: string
  commission: string
  value_per_unit: string
  risk_override: string
  setup: string
  notes: string
}

const EMPTY: FormState = {
  symbol: '',
  direction: 'long',
  opened_at: '',
  closed_at: '',
  volume: '1',
  entry_price: '',
  exit_price: '',
  initial_stop: '',
  initial_target: '',
  gross_profit: '',
  commission: '',
  value_per_unit: '',
  risk_override: '',
  setup: '',
  notes: '',
}

function toNumber(value: string): number | null {
  if (!value.trim()) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function ManualTradeDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<FormState>(EMPTY)
  const [error, setError] = useState<string | null>(null)

  const set = (patch: Partial<FormState>) => setForm((current) => ({ ...current, ...patch }))

  const create = useMutation({
    mutationFn: () =>
      api.post<Trade>('/trades', {
        symbol: form.symbol.trim(),
        direction: form.direction,
        opened_at: new Date(form.opened_at).toISOString(),
        closed_at: form.closed_at ? new Date(form.closed_at).toISOString() : null,
        volume: toNumber(form.volume) ?? 1,
        entry_price: toNumber(form.entry_price) ?? 0,
        exit_price: toNumber(form.exit_price),
        initial_stop: toNumber(form.initial_stop),
        initial_target: toNumber(form.initial_target),
        gross_profit: toNumber(form.gross_profit) ?? 0,
        commission: toNumber(form.commission) ?? 0,
        value_per_unit: toNumber(form.value_per_unit) ?? 0,
        risk_override: toNumber(form.risk_override),
        setup: form.setup,
        notes: form.notes,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries()
      onClose()
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : 'Could not save the trade'),
  })

  const valid = form.symbol.trim() && form.opened_at && toNumber(form.entry_price) !== null

  return (
    <Dialog
      title="Add a trade by hand"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!valid}
            loading={create.isPending}
            onClick={() => {
              setError(null)
              create.mutate()
            }}
          >
            Save trade
          </Button>
        </>
      }
    >
      <p className="mb-4 text-sm text-[var(--tz-text-muted)]">
        For trades that never went through MetaTrader. Leave profit blank and TradeZulu will work
        it out from the prices, as long as you give it a value per point.
      </p>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Symbol">
          <input
            className="tz-input"
            placeholder="EURUSD"
            value={form.symbol}
            onChange={(event) => set({ symbol: event.target.value.toUpperCase() })}
          />
        </Field>
        <Field label="Direction">
          <select
            className="tz-input"
            value={form.direction}
            onChange={(event) => set({ direction: event.target.value as 'long' | 'short' })}
          >
            <option value="long">Long</option>
            <option value="short">Short</option>
          </select>
        </Field>

        <Field label="Opened">
          <input
            type="datetime-local"
            className="tz-input"
            value={form.opened_at}
            onChange={(event) => set({ opened_at: event.target.value })}
          />
        </Field>
        <Field label="Closed">
          <input
            type="datetime-local"
            className="tz-input"
            value={form.closed_at}
            onChange={(event) => set({ closed_at: event.target.value })}
          />
        </Field>

        <Field label="Volume (lots)">
          <input
            type="number"
            step="0.01"
            className="tz-input"
            value={form.volume}
            onChange={(event) => set({ volume: event.target.value })}
          />
        </Field>
        <Field
          label="Value per 1.0 price move, per lot"
          hint="EURUSD is 100000, XAUUSD is usually 100. Used to turn price distance into money."
        >
          <input
            type="number"
            step="any"
            className="tz-input"
            placeholder="100000"
            value={form.value_per_unit}
            onChange={(event) => set({ value_per_unit: event.target.value })}
          />
        </Field>

        <Field label="Entry price">
          <input
            type="number"
            step="any"
            className="tz-input"
            value={form.entry_price}
            onChange={(event) => set({ entry_price: event.target.value })}
          />
        </Field>
        <Field label="Exit price">
          <input
            type="number"
            step="any"
            className="tz-input"
            value={form.exit_price}
            onChange={(event) => set({ exit_price: event.target.value })}
          />
        </Field>

        <Field label="Initial stop">
          <input
            type="number"
            step="any"
            className="tz-input"
            value={form.initial_stop}
            onChange={(event) => set({ initial_stop: event.target.value })}
          />
        </Field>
        <Field label="Initial target">
          <input
            type="number"
            step="any"
            className="tz-input"
            value={form.initial_target}
            onChange={(event) => set({ initial_target: event.target.value })}
          />
        </Field>

        <Field label="Gross profit" hint="Leave blank to derive it from the prices.">
          <input
            type="number"
            step="any"
            className="tz-input"
            value={form.gross_profit}
            onChange={(event) => set({ gross_profit: event.target.value })}
          />
        </Field>
        <Field label="Commission" hint="Negative, as your broker reports it.">
          <input
            type="number"
            step="any"
            className="tz-input"
            value={form.commission}
            onChange={(event) => set({ commission: event.target.value })}
          />
        </Field>

        <Field label="Setup" className="sm:col-span-2">
          <input
            className="tz-input"
            placeholder="London breakout"
            value={form.setup}
            onChange={(event) => set({ setup: event.target.value })}
          />
        </Field>

        <Field label="Notes" className="sm:col-span-2">
          <textarea
            className="tz-input min-h-20"
            value={form.notes}
            onChange={(event) => set({ notes: event.target.value })}
          />
        </Field>
      </div>

      {error && <p className="mt-3 text-sm text-[var(--tz-loss-text)]">{error}</p>}
    </Dialog>
  )
}
