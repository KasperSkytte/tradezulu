import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, use, useEffect, useMemo } from 'react'
import type { ReactNode } from 'react'
import { api } from './api'
import { setClock, setTimeDisplay } from './format'
import type { Account, AppSettings } from './types'

const FALLBACK: AppSettings = {
  general: {
    timezone: 'UTC',
    currency: 'USD',
    currency_symbol: '$',
    week_starts_on: 'monday',
    default_period: 'last_30_days',
    date_format: 'yyyy-MM-dd',
    time_format: '24h',
    times: 'broker',
    theme: 'dark',
    accent: 'jade',
    colorblind_mode: false,
    show_amounts: false,
  },
  risk: {
    breakeven_threshold_r: 0.1,
    breakeven_handling: 'excluded',
    breakeven_threshold_money: 1,
    breakeven_threshold_percent: 0,
    fallback_risk_mode: 'percent_of_balance',
    fixed_risk_amount: 100,
    risk_percent: 1,
    include_commission_in_pnl: true,
    include_swap_in_pnl: true,
    r_uses_net_pnl: true,
  },
  stats: {
    risk_free_rate: 0,
    trading_days_per_year: 252,
    sharpe_basis: 'daily',
    min_trades_for_score: 10,
  },
  zulu_score: { weights: {}, targets: {} },
  news: {
    provider: 'forexfactory',
    countries: ['us'],
    importance: 1,
    currencies: ['USD'],
    impacts: ['High'],
    range: 'upcoming',
  },
  tags: {
    categories: [
      { value: 'setup', label: 'Setup' },
      { value: 'mistake', label: 'Mistake' },
      { value: 'emotion', label: 'Behaviour' },
    ],
  },
  mt5: {
    sync_mode: 'ea',
    restart_weekday: 6,
    restart_hour: 3,
    auto_sync_on_load: true,
    auto_sync_min_interval_seconds: 120,
    history_days_on_full_sync: 730,
  },
  charts: {
    provider: 'klinecharts',
    default_timeframe: 'M15',
    collect_timeframe: 'M5',
    history_days_before: 1,
    history_days_after: 1,
    zoom_hours: 2,
    show_high_low: true,
    tradingview_prefix: '',
    symbol_map: {},
  },
}

interface SettingsState {
  settings: AppSettings
  loading: boolean
  currency: string
  /** Whether currency figures may be shown. Off by default so a screenshot of
   *  the dashboard says how the account is doing without saying what it is
   *  worth. */
  showAmounts: boolean
  weekStartsOn: 0 | 1
  /** For the few places that format a time themselves, because they need the
   *  configured timezone that the date-fns helpers do not take. */
  hour12: boolean
  save: (patch: DeepPartial<AppSettings>) => Promise<AppSettings>
  saving: boolean
  setTheme: (theme: 'dark' | 'light' | 'system') => void
}

export type DeepPartial<T> = {
  [K in keyof T]?: T[K] extends Record<string, unknown> ? DeepPartial<T[K]> : T[K]
}

const SettingsContext = createContext<SettingsState | null>(null)

function applyTheme(theme: 'dark' | 'light' | 'system') {
  const dark =
    theme === 'dark' ||
    (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  document.documentElement.classList.toggle('dark', dark)
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute('content', dark ? '#0b0d13' : '#f6f7fb')
  localStorage.setItem('tz-theme', theme)
}

export function SettingsProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.get<AppSettings>('/settings'),
    staleTime: 60_000,
  })

  const mutation = useMutation({
    mutationFn: (patch: DeepPartial<AppSettings>) => api.put<AppSettings>('/settings', patch),
    onSuccess: (next) => {
      queryClient.setQueryData(['settings'], next)
      // Risk and timezone changes rewrite every derived number server-side.
      void queryClient.invalidateQueries({ queryKey: ['stats'] })
      void queryClient.invalidateQueries({ queryKey: ['trades'] })
      void queryClient.invalidateQueries({ queryKey: ['calendar'] })
    },
  })

  const settings = data ?? FALLBACK

  // Which clock the journal is written in needs the broker's, and only the
  // accounts know that. Cached hard: it changes when a broker moves on or off
  // summer time, not between page views.
  const { data: accounts = [] } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => api.get<Account[]>('/accounts'),
    staleTime: 300_000,
  })

  useEffect(() => {
    if (data) applyTheme(data.general.theme)
  }, [data])

  useEffect(() => {
    document.documentElement.classList.toggle('cb', settings.general.colorblind_mode)
  }, [settings.general.colorblind_mode])

  // Every time in the journal is written by the helpers in lib/format, which
  // are plain functions. This is what tells them which clock to use; the
  // re-render this provider does on a settings change is what redraws them.
  setClock(settings.general.time_format === '12h' ? '12h' : '24h')
  setTimeDisplay({
    mode: settings.general.times === 'local' ? 'local' : 'broker',
    zone: settings.general.timezone || 'UTC',
    offsets: new Map(
      accounts
        .filter((account) => account.broker_utc_offset_minutes !== null)
        .map((account) => [account.id, account.broker_utc_offset_minutes as number]),
    ),
    // For the handful of times not tied to one account. The default account is
    // the one whose trades fill the journal.
    fallback:
      (accounts.find((account) => account.is_default) ?? accounts[0])
        ?.broker_utc_offset_minutes ?? null,
  })

  // Follow the OS while the user has picked "system".
  useEffect(() => {
    if (settings.general.theme !== 'system') return
    const media = window.matchMedia('(prefers-color-scheme: dark)')
    const listener = () => applyTheme('system')
    media.addEventListener('change', listener)
    return () => media.removeEventListener('change', listener)
  }, [settings.general.theme])

  const value = useMemo<SettingsState>(
    () => ({
      settings,
      loading: isLoading,
      currency: settings.general.currency_symbol || '$',
      showAmounts: settings.general.show_amounts ?? false,
      weekStartsOn: settings.general.week_starts_on === 'sunday' ? 0 : 1,
      hour12: settings.general.time_format === '12h',
      save: (patch) => mutation.mutateAsync(patch),
      saving: mutation.isPending,
      setTheme: (theme) => {
        applyTheme(theme)
        void mutation.mutateAsync({ general: { theme } })
      },
    }),
    [settings, isLoading, mutation],
  )

  return <SettingsContext value={value}>{children}</SettingsContext>
}

export function useSettings(): SettingsState {
  const context = use(SettingsContext)
  if (!context) throw new Error('useSettings must be used inside <SettingsProvider>')
  return context
}

/** The tag groups, with "Other" appended.
 *
 *  Other is not stored: it is where a tag lands when its category is not one of
 *  the configured ones, which happens whenever a group is renamed or removed
 *  while tags still point at it. Without it those tags vanish from the menus
 *  while still being attached to trades.
 */
export function useTagCategories(): { value: string; label: string }[] {
  const { settings } = useSettings()
  const configured = settings.tags?.categories ?? []
  return [...configured.filter((c) => c.value && c.value !== 'custom'),
          { value: 'custom', label: 'Other' }]
}

/** Whether the interface is currently dark.
 *
 *  Read from the setting rather than from the html class, because an embedded
 *  widget is built inside an effect that can run before the class is applied --
 *  and, reading the DOM, would never re-run when the theme changed. It would
 *  come up light on a dark page and stay that way until reload.
 */
export function useIsDark(): boolean {
  const { settings } = useSettings()
  const theme = settings.general.theme
  if (theme === 'system') {
    return typeof window !== 'undefined'
      && window.matchMedia('(prefers-color-scheme: dark)').matches
  }
  return theme === 'dark'
}
