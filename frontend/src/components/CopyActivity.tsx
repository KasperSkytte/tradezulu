/** The copier's audit trail: what it did, and what it refused to do. */

import { CheckCircle2, CircleSlash, MinusCircle, XCircle } from 'lucide-react'
import type { CopyEvent, SlaveAccount } from '../lib/types'
import { EmptyState } from './ui'

const OUTCOME = {
  ok: { icon: CheckCircle2, className: 'text-gain-400' },
  dry_run: { icon: CircleSlash, className: 'text-[#eab308]' },
  skipped: { icon: MinusCircle, className: 'text-[var(--tz-text-muted)]' },
  halted: { icon: XCircle, className: 'text-loss-400' },
  failed: { icon: XCircle, className: 'text-loss-400' },
} as const

export function CopyActivity({
  events,
  accounts,
}: {
  events: CopyEvent[]
  accounts: SlaveAccount[]
}) {
  if (events.length === 0) {
    return (
      <EmptyState
        title="Nothing yet"
        description="Once a slave is copying, every open, close, stop move and refusal shows up here with the reason."
      />
    )
  }

  const nameFor = (id: number | null) =>
    accounts.find((account) => account.id === id)?.name ?? 'unknown account'

  return (
    <div className="-mx-2 max-h-96 overflow-y-auto">
      <table className="w-full text-sm">
        <tbody>
          {events.map((event) => {
            const style = OUTCOME[event.outcome as keyof typeof OUTCOME] ?? OUTCOME.skipped
            const Icon = style.icon
            return (
              <tr key={event.id} className="border-b border-[var(--tz-border)] last:border-0">
                <td className="py-2 pl-2 pr-3 align-top">
                  <Icon size={15} className={style.className} />
                </td>
                <td className="py-2 pr-3 align-top whitespace-nowrap text-[var(--tz-text-faint)]">
                  {new Date(event.created_at).toLocaleTimeString()}
                </td>
                <td className="py-2 pr-3 align-top whitespace-nowrap">
                  {nameFor(event.slave_account_id)}
                </td>
                <td className="py-2 pr-3 align-top whitespace-nowrap font-medium">
                  {event.action}
                  {event.symbol ? ` ${event.symbol}` : ''}
                  {event.volume ? ` ${event.volume}` : ''}
                </td>
                <td className="py-2 pr-2 align-top text-[var(--tz-text-muted)]">
                  {event.message}
                  {event.rule ? (
                    <span className="ml-1 text-[var(--tz-text-faint)]">({event.rule})</span>
                  ) : null}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
