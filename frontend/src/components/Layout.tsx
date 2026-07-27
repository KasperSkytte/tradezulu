import { NavLink, Outlet, useLocation } from 'react-router-dom'
import {
  BarChart3,
  CalendarDays,
  LayoutDashboard,
  ListOrdered,
  Copy,
  LogOut,
  Menu,
  Moon,
  Settings as SettingsIcon,
  Sun,
  X,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import clsx from 'clsx'
import { useAuth } from '../lib/auth'
import { useSettings } from '../lib/settings'
import { PeriodPicker } from './PeriodPicker'
import { SyncButton } from './SyncButton'
import { ZuluMark } from './ZuluMark'

const NAV = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/trades', label: 'Trades', icon: ListOrdered, end: false },
  { to: '/accounts', label: 'Accounts', icon: Copy, end: false },
  { to: '/calendar', label: 'Calendar', icon: CalendarDays, end: false },
  { to: '/reports', label: 'Reports', icon: BarChart3, end: false },
  { to: '/settings', label: 'Settings', icon: SettingsIcon, end: false },
]

const PAGE_TITLES: Record<string, string> = {
  '/': 'Dashboard',
  '/trades': 'Trades',
  '/accounts': 'Accounts',
  '/calendar': 'Calendar',
  '/reports': 'Reports',
  '/settings': 'Settings',
}

export function Layout() {
  const { user, logout } = useAuth()
  const { settings, setTheme } = useSettings()
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)

  useEffect(() => setMobileOpen(false), [location.pathname])

  const dark = settings.general.theme !== 'light'
  const title =
    PAGE_TITLES[location.pathname] ??
    (location.pathname.startsWith('/trades') ? 'Trade' : 'TradeZulu')
  const showPeriod =
    !location.pathname.startsWith('/settings') && !location.pathname.startsWith('/calendar')

  return (
    <div className="flex min-h-full">
      {/* Desktop sidebar ------------------------------------------------ */}
      <aside className="tz-no-print sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-[var(--tz-border)] bg-[var(--tz-bg-subtle)] px-3 py-4 lg:flex">
        <div className="mb-6 flex items-center gap-2 px-2">
          <ZuluMark className="h-7 w-7" />
          <span className="text-lg font-semibold tracking-tight">
            Trade<span className="text-zulu-400">Zulu</span>
          </span>
        </div>

        <nav className="flex flex-1 flex-col gap-0.5">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={navClass}>
              <Icon size={17} strokeWidth={1.9} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-4 border-t border-[var(--tz-border)] pt-3">
          <button
            type="button"
            onClick={() => setTheme(dark ? 'light' : 'dark')}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-[var(--tz-text-muted)] transition-colors hover:bg-[var(--tz-surface-hover)] hover:text-[var(--tz-text)]"
          >
            {dark ? <Sun size={17} strokeWidth={1.9} /> : <Moon size={17} strokeWidth={1.9} />}
            {dark ? 'Light mode' : 'Dark mode'}
          </button>
          <button
            type="button"
            onClick={() => void logout()}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-[var(--tz-text-muted)] transition-colors hover:bg-[var(--tz-surface-hover)] hover:text-[var(--tz-text)]"
          >
            <LogOut size={17} strokeWidth={1.9} />
            Sign out
          </button>
          <p className="px-3 pt-2 text-xs text-[var(--tz-text-faint)]">
            Signed in as {user?.username}
          </p>
        </div>
      </aside>

      {/* Main ------------------------------------------------------------ */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="tz-no-print sticky top-0 z-40 border-b border-[var(--tz-border)] bg-[var(--tz-bg)]/85 backdrop-blur-md">
          <div className="flex items-center gap-2 px-3 py-2.5 sm:px-5">
            <button
              type="button"
              className="tz-btn tz-btn-ghost px-2 lg:hidden"
              aria-label="Open menu"
              onClick={() => setMobileOpen(true)}
            >
              <Menu size={18} />
            </button>
            <h1 className="mr-auto truncate text-base font-semibold tracking-tight sm:text-lg">
              {title}
            </h1>
            {showPeriod && <PeriodPicker />}
            <SyncButton />
          </div>
        </header>

        <main className="min-w-0 flex-1 px-3 py-4 pb-24 sm:px-5 lg:pb-8">
          <Outlet />
        </main>
      </div>

      {/* Mobile drawer --------------------------------------------------- */}
      {mobileOpen && (
        <div className="tz-no-print fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />
          <div className="tz-fade-in absolute left-0 top-0 flex h-full w-64 flex-col border-r border-[var(--tz-border)] bg-[var(--tz-bg-subtle)] px-3 py-4">
            <div className="mb-6 flex items-center justify-between px-2">
              <div className="flex items-center gap-2">
                <ZuluMark className="h-7 w-7" />
                <span className="text-lg font-semibold">
                  Trade<span className="text-zulu-400">Zulu</span>
                </span>
              </div>
              <button
                type="button"
                aria-label="Close menu"
                onClick={() => setMobileOpen(false)}
                className="text-[var(--tz-text-muted)]"
              >
                <X size={19} />
              </button>
            </div>
            <nav className="flex flex-1 flex-col gap-0.5">
              {NAV.map(({ to, label, icon: Icon, end }) => (
                <NavLink key={to} to={to} end={end} className={navClass}>
                  <Icon size={17} strokeWidth={1.9} />
                  {label}
                </NavLink>
              ))}
            </nav>
            <button
              type="button"
              onClick={() => void logout()}
              className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-[var(--tz-text-muted)]"
            >
              <LogOut size={17} strokeWidth={1.9} />
              Sign out
            </button>
          </div>
        </div>
      )}

      {/* Mobile bottom bar ----------------------------------------------- */}
      <nav className="tz-no-print fixed inset-x-0 bottom-0 z-40 flex border-t border-[var(--tz-border)] bg-[var(--tz-bg)]/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              clsx(
                'flex flex-1 flex-col items-center gap-0.5 py-2 text-[0.65rem] font-medium transition-colors',
                isActive ? 'text-zulu-400' : 'text-[var(--tz-text-muted)]',
              )
            }
          >
            <Icon size={19} strokeWidth={1.9} />
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}

function navClass({ isActive }: { isActive: boolean }) {
  return clsx(
    'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors',
    isActive
      ? 'bg-zulu-500/12 text-zulu-400'
      : 'text-[var(--tz-text-muted)] hover:bg-[var(--tz-surface-hover)] hover:text-[var(--tz-text)]',
  )
}
