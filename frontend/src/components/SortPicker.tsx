/**
 * How the trade list is ordered, beside the filter that decides what is in it.
 *
 * The column headers have always sorted, and still do. They are not enough on
 * their own: half of them are hidden on a laptop and all of them on a phone,
 * where the table becomes cards and there is no header row to click — so the
 * only way to sort by risk on a phone was to turn it sideways. This names the
 * same columns in a place that is always there, and puts the choice in the URL
 * with the filters, so it survives a reload and travels with a shared link.
 */

import { useEffect, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react'
import clsx from 'clsx'
import { useFilters } from '../lib/filters'
import { Button } from './ui'

/** The columns the server will order by, in the order they read as questions:
 *  when, what, how much did it make, how well was it planned. */
export const SORT_OPTIONS: { key: string; label: string }[] = [
  { key: 'closed_at', label: 'Closed' },
  { key: 'opened_at', label: 'Opened' },
  { key: 'symbol', label: 'Symbol' },
  { key: 'net_pnl', label: 'Net P&L' },
  { key: 'realized_r', label: 'R multiple' },
  { key: 'planned_r', label: 'Planned R' },
  { key: 'risk', label: 'Risk' },
  { key: 'volume', label: 'Size' },
  { key: 'duration', label: 'Held' },
]

export function sortLabel(key: string): string {
  return SORT_OPTIONS.find((option) => option.key === key)?.label ?? 'Closed'
}

export function SortPicker() {
  const { filters, setSort, setOrder } = useFilters()
  const [open, setOpen] = useState(false)
  const panel = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (!panel.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [open])

  const descending = filters.order === 'desc'

  return (
    <div className="relative" ref={panel}>
      <Button onClick={() => setOpen((value) => !value)} icon={<ArrowUpDown size={15} />}>
        {sortLabel(filters.sort)}
        {descending ? <ArrowDown size={13} /> : <ArrowUp size={13} />}
      </Button>

      {open && (
        <div className="tz-card tz-fade-in absolute right-0 z-50 mt-2 w-[min(15rem,calc(100vw-1.5rem))] p-2">
          <ul className="space-y-0.5">
            {SORT_OPTIONS.map((option) => {
              const active = filters.sort === option.key
              return (
                <li key={option.key}>
                  <button
                    type="button"
                    onClick={() => setSort(option.key)}
                    className={clsx(
                      'flex w-full items-center justify-between rounded-md px-2.5 py-1.5 text-left text-sm',
                      active
                        ? 'bg-[var(--tz-surface-raised)] text-[var(--tz-text)]'
                        : 'text-[var(--tz-text-muted)] hover:bg-[var(--tz-surface-raised)] hover:text-[var(--tz-text)]',
                    )}
                  >
                    {option.label}
                    {/* On the column in use, the arrow says which way and
                        pressing it again turns it round. */}
                    {active &&
                      (descending ? <ArrowDown size={13} /> : <ArrowUp size={13} />)}
                  </button>
                </li>
              )
            })}
          </ul>

          <div className="mt-2 grid grid-cols-2 gap-1 border-t border-[var(--tz-border)] pt-2">
            {(
              [
                ['desc', 'Highest first'],
                ['asc', 'Lowest first'],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setOrder(value)}
                className={clsx(
                  'rounded-md px-2 py-1.5 text-xs',
                  filters.order === value
                    ? 'bg-[var(--tz-surface-raised)] text-[var(--tz-text)]'
                    : 'text-[var(--tz-text-muted)] hover:bg-[var(--tz-surface-raised)] hover:text-[var(--tz-text)]',
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
