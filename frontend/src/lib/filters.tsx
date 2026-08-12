/** The date range and trade filters shared by the dashboard, trades list and
 *  reports. Kept in the URL so a view can be bookmarked or shared. */

import { createContext, use, useCallback, useEffect, useMemo } from 'react'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { api } from './api'
import type { QueryValue } from './api'
import { resolvePeriod } from './period'
import { useSettings } from './settings'
import type { Account } from './types'

/** Which account the whole application is looking at.
 *
 *  Not a filter but a scope, which is why it sits beside the date range rather
 *  than inside the filter panel. Trades from different accounts are different
 *  pools of money: adding their profits together is fine, but a return, a
 *  drawdown or an equity curve across them describes a portfolio nobody held.
 *  The server withholds those figures when several accounts are in scope, so
 *  "all" is honest rather than wrong -- but a single account is the default,
 *  because that is what the numbers are actually about. */
export type AccountScope = number | 'all'

export type SortOrder = 'asc' | 'desc'

export interface Filters {
  accountId: AccountScope | undefined
  /** How the trade list is ordered. Only the trades page reads these. */
  sort: string
  order: SortOrder
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
  accounts: Account[]
  /** Only the account scope, for views that take nothing else. */
  accountParams: Record<string, QueryValue>
  setAccount: (scope: AccountScope) => void
  setPeriod: (period: string) => void
  setRange: (start: string, end: string) => void
  /** Order the trade list. Choosing the column already sorted on flips it. */
  setSort: (key: string) => void
  setOrder: (order: SortOrder) => void
  update: (patch: Partial<Filters>) => void
  reset: () => void
  activeCount: number
}

const FiltersContext = createContext<FiltersState | null>(null)

function parseList(value: string | null): string[] {
  return value ? value.split(',').filter(Boolean) : []
}

/** Everything the filter bar and the pickers own, and nothing else.
 *
 *  Listed rather than "every parameter" so a page's own state -- the month the
 *  calendar is showing, the section the settings page is on -- is never
 *  dragged onto a different page.
 */
const FILTER_KEYS = [
  'period', 'start', 'end', 'account', 'symbols', 'tags',
  'directions', 'outcomes', 'q', 'minR', 'maxR', 'excluded',
  // Not a filter -- it changes the order, not which trades there are -- but it
  // belongs to the same bar, the same URL and the same "where was I" as the
  // rest. Kept out of the active count for the same reason.
  'sort', 'order',
] as const

const REMEMBERED = 'tz-filters'

/**
 * Carry the filters across a navigation.
 *
 * They live in the URL, which is right -- a link to a filtered view is worth
 * having -- but the sidebar links are plain paths, so choosing "this week" on
 * the dashboard and clicking Trades landed on the default period again, and
 * the same for whichever account was being looked at. Nobody means "show me
 * a different fortnight now" by clicking Trades.
 *
 * The URL still wins wherever it says anything: a shared or bookmarked link
 * opens on what it describes, and only a page arriving with no filters at all
 * takes the remembered ones.
 */
function useStickyFilters(
  searchParams: URLSearchParams,
  setSearchParams: ReturnType<typeof useSearchParams>[1],
) {
  useEffect(() => {
    const kept = new URLSearchParams()
    for (const key of FILTER_KEYS) {
      const value = searchParams.get(key)
      if (value) kept.set(key, value)
    }
    if ([...kept.keys()].length) localStorage.setItem(REMEMBERED, kept.toString())
  }, [searchParams])

  useEffect(() => {
    if (FILTER_KEYS.some((key) => searchParams.has(key))) return
    const kept = localStorage.getItem(REMEMBERED)
    if (!kept) return
    // Replaced rather than pushed: this is the same view arriving with what it
    // was already showing, not somewhere the back button should return to.
    setSearchParams(new URLSearchParams(kept), { replace: true })
  }, [searchParams, setSearchParams])
}

export function FiltersProvider({ children }: { children: ReactNode }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const { settings, weekStartsOn } = useSettings()

  useStickyFilters(searchParams, setSearchParams)

  const { data: accounts = [] } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => api.get<Account[]>('/accounts'),
    staleTime: 300_000,
  })

  // No account in the URL means "the one you normally look at", which is the
  // default account. Until they load there is nothing to scope to; the server
  // withholds the per-account figures in that instant rather than guessing.
  const raw = searchParams.get('account')
  const accountId = useMemo<AccountScope | undefined>(() => {
    if (raw === 'all') return 'all'
    if (raw && Number.isFinite(Number(raw))) return Number(raw)
    const fallback = accounts.find((entry) => entry.is_default) ?? accounts[0]
    return fallback?.id
  }, [raw, accounts])

  const period = searchParams.get('period') ?? settings.general.default_period ?? 'last_30_days'
  const resolved = useMemo(
    () => resolvePeriod(period, weekStartsOn),
    [period, weekStartsOn],
  )

  const filters = useMemo<Filters>(
    () => ({
      accountId,
      period: searchParams.get('start') && searchParams.get('end') ? 'custom' : period,
      sort: searchParams.get('sort') ?? 'closed_at',
      order: searchParams.get('order') === 'asc' ? 'asc' : 'desc',
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
    [searchParams, period, resolved, accountId],
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

  const setAccount = useCallback(
    (scope: AccountScope) => {
      write((next) => next.set('account', String(scope)))
    },
    [write],
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

  const setSort = useCallback(
    (key: string) => {
      write((next) => {
        // Choosing the column already in use turns it round, which is what
        // clicking a table header has always done and what anyone expects of
        // a sort control that names the same columns.
        const flip = (next.get('sort') ?? 'closed_at') === key
        const order = next.get('order') === 'asc' ? 'asc' : 'desc'
        next.set('sort', key)
        next.set('order', flip && order === 'desc' ? 'asc' : 'desc')
      })
    },
    [write],
  )

  const setOrder = useCallback(
    (order: SortOrder) => {
      write((next) => next.set('order', order))
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

  /** Just the account, for the views that scope by it and nothing else.
   *
   *  The calendar and the day behind it are about a month, not about the date
   *  range or the symbol filters, and neither of those is even on screen
   *  there. They still belong to one account: a slave added on Tuesday
   *  otherwise starts contributing to the master's trading days on Tuesday,
   *  silently, with no control anywhere to say otherwise. */
  const accountParams = useMemo<Record<string, QueryValue>>(
    () => ({
      account_id: typeof filters.accountId === 'number' ? filters.accountId : undefined,
    }),
    [filters.accountId],
  )

  const params = useMemo<Record<string, QueryValue>>(
    () => ({
      account_id: typeof filters.accountId === 'number' ? filters.accountId : undefined,
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
    () => ({
      filters, params, accountParams, accounts,
      setAccount, setPeriod, setRange, setSort, setOrder, update, reset, activeCount,
    }),
    [
      filters, params, accountParams, accounts,
      setAccount, setPeriod, setRange, setSort, setOrder, update, reset, activeCount,
    ],
  )

  return <FiltersContext value={value}>{children}</FiltersContext>
}

export function useFilters(): FiltersState {
  const context = use(FiltersContext)
  if (!context) throw new Error('useFilters must be used inside <FiltersProvider>')
  return context
}
