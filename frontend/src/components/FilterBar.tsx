import { useQuery } from '@tanstack/react-query'
import { Filter, Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { api } from '../lib/api'
import { useFilters } from '../lib/filters'
import type { Tag } from '../lib/types'
import { Button, Chip } from './ui'

const DIRECTIONS = [
  { value: 'long', label: 'Long' },
  { value: 'short', label: 'Short' },
]

const OUTCOMES = [
  { value: 'win', label: 'Wins' },
  { value: 'loss', label: 'Losses' },
  { value: 'breakeven', label: 'Breakevens' },
]

export function FilterBar() {
  const { filters, update, reset, activeCount, accountParams } = useFilters()
  const [open, setOpen] = useState(false)
  const [searchDraft, setSearchDraft] = useState(filters.search)
  const panel = useRef<HTMLDivElement>(null)

  // Symbols this account has traded, not every symbol in the database: a
  // filter offering instruments the account in view has never touched is a
  // list of ways to empty the page.
  const { data: symbols = [] } = useQuery({
    queryKey: ['symbols', accountParams],
    queryFn: () => api.get<string[]>('/trades/symbols', accountParams),
    staleTime: 300_000,
  })
  const { data: tags = [] } = useQuery({
    queryKey: ['tags'],
    queryFn: () => api.get<Tag[]>('/tags'),
    staleTime: 300_000,
  })

  useEffect(() => setSearchDraft(filters.search), [filters.search])

  // Debounce the free-text search so every keystroke is not a request.
  useEffect(() => {
    if (searchDraft === filters.search) return
    const timer = setTimeout(() => update({ search: searchDraft }), 350)
    return () => clearTimeout(timer)
  }, [searchDraft, filters.search, update])

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (!panel.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [open])

  const toggle = <T,>(list: T[], value: T): T[] =>
    list.includes(value) ? list.filter((item) => item !== value) : [...list, value]

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-0 flex-1 sm:max-w-xs">
        <Search
          size={15}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--tz-text-faint)]"
        />
        <input
          className="tz-input pl-9 text-sm"
          placeholder="Search notes, symbol, setup…"
          value={searchDraft}
          onChange={(event) => setSearchDraft(event.target.value)}
        />
        {searchDraft && (
          <button
            type="button"
            aria-label="Clear search"
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[var(--tz-text-faint)] hover:text-[var(--tz-text)]"
            onClick={() => setSearchDraft('')}
          >
            <X size={14} />
          </button>
        )}
      </div>

      <div className="relative" ref={panel}>
        <Button
          onClick={() => setOpen((value) => !value)}
          icon={<Filter size={15} />}
          className={clsx(activeCount > 0 && 'border-zulu-500/60 text-zulu-400')}
        >
          Filters
          {activeCount > 0 && (
            <span className="ml-0.5 rounded-full bg-zulu-500 px-1.5 text-[0.65rem] font-semibold text-white">
              {activeCount}
            </span>
          )}
        </Button>

        {open && (
          <div className="tz-card tz-fade-in absolute right-0 z-50 mt-2 max-h-[70vh] w-[min(22rem,calc(100vw-1.5rem))] overflow-y-auto p-4">
            <Section title="Direction">
              <div className="flex flex-wrap gap-1.5">
                {DIRECTIONS.map((option) => (
                  <FilterPill
                    key={option.value}
                    active={filters.directions.includes(option.value)}
                    onClick={() =>
                      update({ directions: toggle(filters.directions, option.value) })
                    }
                  >
                    {option.label}
                  </FilterPill>
                ))}
              </div>
            </Section>

            <Section title="Outcome">
              <div className="flex flex-wrap gap-1.5">
                {OUTCOMES.map((option) => (
                  <FilterPill
                    key={option.value}
                    active={filters.outcomes.includes(option.value)}
                    onClick={() => update({ outcomes: toggle(filters.outcomes, option.value) })}
                  >
                    {option.label}
                  </FilterPill>
                ))}
              </div>
            </Section>

            {symbols.length > 0 && (
              <Section title="Symbol">
                <div className="flex flex-wrap gap-1.5">
                  {symbols.map((symbol) => (
                    <FilterPill
                      key={symbol}
                      active={filters.symbols.includes(symbol)}
                      onClick={() => update({ symbols: toggle(filters.symbols, symbol) })}
                    >
                      {symbol}
                    </FilterPill>
                  ))}
                </div>
              </Section>
            )}

            {tags.length > 0 && (
              <Section title="Tags (all selected must match)">
                <div className="flex flex-wrap gap-1.5">
                  {tags.map((tag) => (
                    <button
                      key={tag.id}
                      type="button"
                      onClick={() => update({ tagIds: toggle(filters.tagIds, tag.id) })}
                      className={clsx(
                        'tz-chip transition-opacity',
                        !filters.tagIds.includes(tag.id) && 'opacity-55 hover:opacity-90',
                      )}
                      style={{
                        backgroundColor: `color-mix(in srgb, ${tag.color} 18%, transparent)`,
                        color: tag.color,
                        border: `1px solid color-mix(in srgb, ${tag.color} 40%, transparent)`,
                      }}
                    >
                      {tag.name}
                    </button>
                  ))}
                </div>
              </Section>
            )}

            <Section title="R multiple range">
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  step="0.1"
                  placeholder="min"
                  className="tz-input text-sm"
                  value={filters.minR}
                  onChange={(event) => update({ minR: event.target.value })}
                />
                <span className="text-[var(--tz-text-faint)]">to</span>
                <input
                  type="number"
                  step="0.1"
                  placeholder="max"
                  className="tz-input text-sm"
                  value={filters.maxR}
                  onChange={(event) => update({ maxR: event.target.value })}
                />
              </div>
            </Section>

            <label className="mt-3 flex cursor-pointer items-center gap-2 text-sm text-[var(--tz-text-muted)]">
              <input
                type="checkbox"
                className="size-4 accent-[var(--color-zulu-500)]"
                checked={filters.includeExcluded}
                onChange={(event) => update({ includeExcluded: event.target.checked })}
              />
              Show trades excluded from statistics
            </label>

            <div className="mt-4 flex gap-2">
              <Button className="flex-1" onClick={reset} disabled={activeCount === 0}>
                Clear all
              </Button>
              <Button variant="primary" className="flex-1" onClick={() => setOpen(false)}>
                Done
              </Button>
            </div>
          </div>
        )}
      </div>

      {activeCount > 0 && (
        <div className="hidden items-center gap-1.5 lg:flex">
          {filters.symbols.map((symbol) => (
            <Chip key={symbol} color="var(--color-zulu-400)">
              {symbol}
            </Chip>
          ))}
          {filters.outcomes.map((outcome) => (
            <Chip key={outcome} color="var(--tz-flat)">
              {outcome}
            </Chip>
          ))}
        </div>
      )}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-4 last:mb-0">
      <p className="tz-label">{title}</p>
      {children}
    </div>
  )
}

function FilterPill({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={clsx(
        'rounded-full border px-2.5 py-1 text-xs font-medium transition-colors',
        active
          ? 'border-zulu-500 bg-zulu-500/15 text-zulu-400'
          : 'border-[var(--tz-border)] text-[var(--tz-text-muted)] hover:border-[var(--tz-border-strong)] hover:text-[var(--tz-text)]',
      )}
    >
      {children}
    </button>
  )
}
