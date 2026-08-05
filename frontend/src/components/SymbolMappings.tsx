/**
 * What this slave calls each of the master's instruments.
 *
 * The copier works this out on its own -- the same instrument is `XAUUSD` at
 * one broker, `XAUUSD+` at another and `XAUUSDm` at a third -- and until now
 * its answers were only visible in the database. A copier deciding by itself
 * which instrument to buy is exactly the thing that should be inspectable, so
 * this shows every mapping it is holding and lets any of them be overruled.
 *
 * Two kinds, kept apart on purpose:
 *
 *  - **Yours** always wins and is never touched by anything here.
 *  - **Worked out** is what the search found. Forgetting one makes the copier
 *    resolve it again on the next heartbeat, which is what you want when the
 *    broker has renamed something and the copier is still holding the old
 *    answer.
 */

import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { Plus, RotateCcw, Trash2 } from 'lucide-react'
import { ApiError, api } from '../lib/api'
import type { SlaveAccount } from '../lib/types'
import { Dialog } from './Dialog'
import { Button } from './ui'

type Row = { from: string; to: string }

export function SymbolMappings({
  account,
  onClose,
  onChanged,
}: {
  account: SlaveAccount
  onClose: () => void
  onChanged: () => void
}) {
  const [rows, setRows] = useState<Row[]>(() =>
    Object.entries(account.symbol_map ?? {}).map(([from, to]) => ({ from, to })),
  )
  const [forget, setForget] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)

  const learned = Object.entries(account.symbol_learned ?? {})
    .filter(([from]) => !forget.includes(from))
    .sort(([a], [b]) => a.localeCompare(b))

  const save = useMutation({
    mutationFn: () =>
      api.put(`/accounts/${account.id}/symbols`, {
        overrides: Object.fromEntries(
          rows.filter((row) => row.from.trim() && row.to.trim()).map((row) => [row.from, row.to]),
        ),
        forget,
      }),
    onSuccess: () => {
      onChanged()
      onClose()
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : 'Could not save that'),
  })

  const setRow = (index: number, patch: Partial<Row>) =>
    setRows((current) => current.map((row, at) => (at === index ? { ...row, ...patch } : row)))

  return (
    <Dialog
      title={`Symbols · ${account.name || account.login}`}
      size="lg"
      onClose={onClose}
      footer={
        <div className="flex w-full items-center justify-between gap-3">
          {error ? (
            <span className="text-sm text-loss-400">{error}</span>
          ) : (
            <span className="text-xs text-[var(--tz-text-faint)]">
              Changes take effect on this account's next heartbeat.
            </span>
          )}
          <div className="flex gap-2">
            <Button onClick={onClose}>Cancel</Button>
            <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>
              Save
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-6">
        <section>
          <h3 className="text-sm font-semibold">Your mappings</h3>
          <p className="mt-1 text-sm text-[var(--tz-text-muted)]">
            Written as the master names it, then as this broker does. These win over anything
            the copier works out for itself.
          </p>

          <div className="mt-3 space-y-2">
            {rows.map((row, index) => (
              <div key={index} className="flex items-center gap-2">
                <input
                  className="tz-input min-w-0 flex-1"
                  placeholder="XAUUSD+"
                  value={row.from}
                  onChange={(event) => setRow(index, { from: event.target.value })}
                />
                <span className="shrink-0 text-[var(--tz-text-faint)]">→</span>
                <input
                  className="tz-input min-w-0 flex-1"
                  placeholder="GOLD"
                  value={row.to}
                  onChange={(event) => setRow(index, { to: event.target.value })}
                />
                <button
                  type="button"
                  aria-label="Remove this mapping"
                  className="tz-btn tz-btn-ghost tz-btn-sm shrink-0"
                  onClick={() => setRows((current) => current.filter((_, at) => at !== index))}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            {!rows.length && (
              <p className="text-sm text-[var(--tz-text-faint)]">
                None. The copier is matching everything on its own.
              </p>
            )}
          </div>

          <button
            type="button"
            className="tz-btn tz-btn-ghost tz-btn-sm mt-3"
            onClick={() => setRows((current) => [...current, { from: '', to: '' }])}
          >
            <Plus size={14} /> Add a mapping
          </button>
        </section>

        <section className="border-t border-[var(--tz-border)] pt-5">
          <h3 className="text-sm font-semibold">Worked out by the copier</h3>
          <p className="mt-1 text-sm text-[var(--tz-text-muted)]">
            Matched against the symbols this broker reports, and remembered so the search runs
            once per instrument rather than on every position change. Forget one to have it
            resolved again — useful if the broker has renamed something.
          </p>

          {learned.length ? (
            <div className="mt-3 overflow-x-auto">
              <table className="tz-table w-full text-sm">
                <thead>
                  <tr>
                    <th className="text-left">Master</th>
                    <th className="text-left">This broker</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {learned.map(([from, to]) => (
                    <tr key={from}>
                      <td className="whitespace-nowrap font-medium">{from}</td>
                      <td className="whitespace-nowrap">{to}</td>
                      <td className="text-right">
                        <button
                          type="button"
                          className="tz-btn tz-btn-ghost tz-btn-sm"
                          title="Work this one out again"
                          onClick={() => setForget((current) => [...current, from])}
                        >
                          <RotateCcw size={13} /> Forget
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="mt-3 text-sm text-[var(--tz-text-faint)]">
              Nothing yet. One appears the first time this account is asked to copy an
              instrument.
            </p>
          )}

          {forget.length > 0 && (
            <p className="mt-3 text-sm text-[var(--tz-text-muted)]">
              {forget.length} to be worked out again on save: {forget.join(', ')}
            </p>
          )}
        </section>

        <p className="border-t border-[var(--tz-border)] pt-4 text-xs text-[var(--tz-text-faint)]">
          Neither list decides anything on its own: a name is only ever used if this broker
          currently reports it, so a mapping to something that has gone away is resolved afresh
          rather than traded blindly.
        </p>
      </div>
    </Dialog>
  )
}
