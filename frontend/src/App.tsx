import { Suspense, lazy } from 'react'
import { Route, Routes } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { Layout } from './components/Layout'
import { FiltersProvider } from './lib/filters'
import { SettingsProvider } from './lib/settings'
import { useAuth } from './lib/auth'
import { LoginPage } from './pages/LoginPage'

// Every page is split out, so an unauthenticated visitor downloads the login
// screen and nothing else — the charting libraries are the bulk of the bundle.
const DashboardPage = lazy(() =>
  import('./pages/DashboardPage').then((module) => ({ default: module.DashboardPage })),
)
const TradesPage = lazy(() =>
  import('./pages/TradesPage').then((module) => ({ default: module.TradesPage })),
)
const TradeDetailPage = lazy(() =>
  import('./pages/TradeDetailPage').then((module) => ({ default: module.TradeDetailPage })),
)
const CalendarPage = lazy(() =>
  import('./pages/CalendarPage').then((module) => ({ default: module.CalendarPage })),
)
const AccountsPage = lazy(() =>
  import('./pages/AccountsPage').then((m) => ({ default: m.AccountsPage })),
)
const ReportsPage = lazy(() =>
  import('./pages/ReportsPage').then((module) => ({ default: module.ReportsPage })),
)
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((module) => ({ default: module.SettingsPage })),
)
const NotFoundPage = lazy(() =>
  import('./pages/NotFoundPage').then((module) => ({ default: module.NotFoundPage })),
)

function Spinner() {
  return (
    <div className="flex h-64 items-center justify-center">
      <Loader2 className="animate-spin text-zulu-400" size={26} />
    </div>
  )
}

export function App() {
  const { user, loading } = useAuth()

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="animate-spin text-zulu-400" size={28} />
      </div>
    )
  }

  if (!user) return <LoginPage />

  return (
    <SettingsProvider>
      <FiltersProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route
              index
              element={
                <Suspense fallback={<Spinner />}>
                  <DashboardPage />
                </Suspense>
              }
            />
            <Route
              path="trades"
              element={
                <Suspense fallback={<Spinner />}>
                  <TradesPage />
                </Suspense>
              }
            />
            <Route
              path="trades/:id"
              element={
                <Suspense fallback={<Spinner />}>
                  <TradeDetailPage />
                </Suspense>
              }
            />
            <Route
              path="accounts"
              element={
                <Suspense fallback={<Spinner />}>
                  <AccountsPage />
                </Suspense>
              }
            />
            <Route
              path="calendar"
              element={
                <Suspense fallback={<Spinner />}>
                  <CalendarPage />
                </Suspense>
              }
            />
            <Route
              path="reports"
              element={
                <Suspense fallback={<Spinner />}>
                  <ReportsPage />
                </Suspense>
              }
            />
            <Route
              path="settings"
              element={
                <Suspense fallback={<Spinner />}>
                  <SettingsPage />
                </Suspense>
              }
            />
            <Route
              path="*"
              element={
                <Suspense fallback={<Spinner />}>
                  <NotFoundPage />
                </Suspense>
              }
            />
          </Route>
        </Routes>
      </FiltersProvider>
    </SettingsProvider>
  )
}
