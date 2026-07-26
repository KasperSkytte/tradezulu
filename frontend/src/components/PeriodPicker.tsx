import { useEffect, useRef, useState } from 'react'
import { CalendarRange, Check, ChevronDown } from 'lucide-react'
import clsx from 'clsx'
import { useFilters } from '../lib/filters'
import { PERIOD_OPTIONS, periodLabel } from '../lib/period'
import { dateOnly } from '../lib/format'

export function PeriodPicker() {
  const { filters, setPeriod, setRange } = useFilters()
  const [open, setOpen] = useState(false)
  const [customStart, setCustomStart] = useState(filters.start)
  const [customEnd, setCustomEnd] = useState(filters.end)
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setCustomStart(filters.start)
    setCustomEnd(filters.end)
  }, [filters.start, filters.end])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const label = filters.period === 'custom' ? 'Custom range' : periodLabel(filters.period)

  return (
    <div className="relative" ref={container}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="tz-btn tz-btn-ghost"
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <CalendarRange size={15} />
        <span className="hidden sm:inline">{label}</span>
        <span className="hidden text-xs text-[var(--tz-text-muted)] md:inline">
          {dateOnly(filters.start, 'd MMM')} – {dateOnly(filters.end, 'd MMM yyyy')}
        </span>
        <span className="sm:hidden text-xs">
          {dateOnly(filters.start, 'd MMM')}–{dateOnly(filters.end, 'd MMM')}
        </span>
        <ChevronDown size={14} className={clsx('transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Select period"
          className="tz-card tz-fade-in absolute right-0 z-50 mt-2 w-[19rem] p-3"
        >
          <div className="max-h-72 overflow-y-auto pr-1">
            {(['recent', 'calendar', 'other'] as const).map((group) => (
              <div key={group} className="mb-2 last:mb-0">
                <p className="tz-label mb-1 capitalize">{group}</p>
                <div className="grid grid-cols-2 gap-1">
                  {PERIOD_OPTIONS.filter((option) => option.group === group).map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      onClick={() => {
                        setPeriod(option.id)
                        setOpen(false)
                      }}
                      className={clsx(
                        'flex items-center justify-between rounded-md px-2 py-1.5 text-left text-sm transition-colors',
                        filters.period === option.id
                          ? 'bg-zulu-500/15 text-zulu-400'
                          : 'hover:bg-[var(--tz-surface-hover)]',
                      )}
                    >
                      {option.label}
                      {filters.period === option.id && <Check size={13} />}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-3 border-t border-[var(--tz-border)] pt-3">
            <p className="tz-label">Custom range</p>
            <div className="flex items-center gap-2">
              <input
                type="date"
                className="tz-input text-sm"
                value={customStart}
                max={customEnd}
                onChange={(event) => setCustomStart(event.target.value)}
              />
              <span className="text-[var(--tz-text-faint)]">–</span>
              <input
                type="date"
                className="tz-input text-sm"
                value={customEnd}
                min={customStart}
                onChange={(event) => setCustomEnd(event.target.value)}
              />
            </div>
            <button
              type="button"
              className="tz-btn tz-btn-primary mt-2 w-full"
              disabled={!customStart || !customEnd || customStart > customEnd}
              onClick={() => {
                setRange(customStart, customEnd)
                setOpen(false)
              }}
            >
              Apply range
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
