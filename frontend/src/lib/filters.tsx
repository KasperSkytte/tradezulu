/** The date range and trade filters shared by the dashboard, trades list and
 *  reports. Kept in the URL so a view can be bookmarked or shared. */

import { createContext, use, useCallback, useMemo } from 'react'
import type { ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { QueryValue } from './api'
import { resolvePeriod } from './period'
import { useSettings } from './settings'

export interface Filters {
  period: string
  start: string
  end: string
  symbols: string[]
  tagIds: number[]
  directions: string[]
  outcomes: string[]
  search: string
  minR: string
  maxR: string
  includeExcluded: boolean
}

interface FiltersState {
  filters: Filters
  /** Query-string parameters for the statistics and trades endpoints. */
  params: Record<string, QueryValue>
  setPeriod: (period: string) => void
  setRange: (start: string, end: string) => void
  update: (patch: Partial<Filters>) => void
  reset: () => void
  activeCount: number
}

const FiltersContext = createContext<FiltersState | null>(null)

function parseList(value: string | null): string[] {
  return value ? value.split(',').filter(Boolean) : []
}

export function FiltersProvider({ children }: { children: ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const { settings, weekStartsOn } = useSettings()

  const period = searchParams.get('period') ?? settings.general.default_period ?? 'last_30_days'
  const resolved = useMemo(
    () => resolvePeriod(period, weekStartsOn),
    [period, weekStartsOn],
  )

  const filters = useMemo<Filters>(
    () => ({
      period: searchParams.get('start') && searchParams.get('end') ? 'custom' : period,
      start: searchParams.get('start') ?? resolved.start,
      end: searchParams.get('end') ?? resolved.end,
      symbols: parseList(searchParams.get('symbols')),
      tagIds: parseList(searchParams.get('tags')).map(Number).filter(Number.isFinite),
      directions: parseList(searchParams.get('directions')),
      outcomes: parseList(searchParams.get('outcomes')),
      search: searchParams.get('q') ?? '',
      minR: searchParams.get('minR') ?? '',
      maxR: searchParams.get('maxR') ?? '',
      includeExcluded: searchParams.get('excluded') === '1',
    }),
    [searchParams, period, resolved],
  )

  const write = useCallback(
    (mutate: (next: URLSearchParams) => void) => {
      setSearchParams(
        (current) => {
          const next = new URLSearchParams(current)
          mutate(next)
          return next
        },
        { replace: true },
      )
    },
    [setSearchParams],
  )

  const setPeriod = useCallback(
    (value: string) => {
      write((next) => {
        next.set('period', value)
        next.delete('start')
        next.delete('end')
      })
    },
    [write],
  )

  const setRange = useCallback(
    (start: string, end: string) => {
      write((next) => {
        next.set('start', start)
        next.set('end', end)
        next.delete('period')
      })
    },
    [write],
  )

  const update = useCallback(
    (patch: Partial<Filters>) => {
      write((next) => {
        const setOrDelete = (key: string, value: string) =>
          value ? next.set(key, value) : next.delete(key)
        if (patch.symbols) setOrDelete('symbols', patch.symbols.join(','))
        if (patch.tagIds) setOrDelete('tags', patch.tagIds.join(','))
        if (patch.directions) setOrDelete('directions', patch.directions.join(','))
        if (patch.outcomes) setOrDelete('outcomes', patch.outcomes.join(','))
        if (patch.search !== undefined) setOrDelete('q', patch.search)
        if (patch.minR !== undefined) setOrDelete('minR', patch.minR)
        if (patch.maxR !== undefined) setOrDelete('maxR', patch.maxR)
        if (patch.includeExcluded !== undefined) {
          if (patch.includeExcluded) next.set('excluded', '1')
          else next.delete('excluded')
        }
      })
    },
    [write],
  )

  const reset = useCallback(() => {
    write((next) => {
      for (const key of ['symbols', 'tags', 'directions', 'outcomes', 'q', 'minR', 'maxR', 'excluded'])
        next.delete(key)
    })
  }, [write])

  const params = useMemo<Record<string, QueryValue>>(
    () => ({
      start: filters.start,
      end: filters.end,
      symbol: filters.symbols,
      tag: filters.tagIds,
      direction: filters.directions,
      outcome: filters.outcomes,
      search: filters.search || undefined,
      min_r: filters.minR || undefined,
      max_r: filters.maxR || undefined,
      include_excluded: filters.includeExcluded || undefined,
    }),
    [filters],
  )

  const activeCount =
    filters.symbols.length +
    filters.tagIds.length +
    filters.directions.length +
    filters.outcomes.length +
    (filters.search ? 1 : 0) +
    (filters.minR ? 1 : 0) +
    (filters.maxR ? 1 : 0)

  const value = useMemo<FiltersState>(
    () => ({ filters, params, setPeriod, setRange, update, reset, activeCount }),
    [filters, params, setPeriod, setRange, update, reset, activeCount],
  )

  return <FiltersContext value={value}>{children}</FiltersContext>
}

export function useFilters(): FiltersState {
  const context = use(FiltersContext)
  if (!context) throw new Error('useFilters must be used inside <FiltersProvider>')
  return context
}
