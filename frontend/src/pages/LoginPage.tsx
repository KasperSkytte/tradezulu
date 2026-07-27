import { useState } from 'react'
import type { FormEvent } from 'react'
import { AlertTriangle, KeyRound, Loader2, User } from 'lucide-react'
import { ApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { ZuluMark } from '../components/ZuluMark'

export function LoginPage() {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await login(username.trim(), password, remember)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : 'Could not sign in')
      setBusy(false)
    }
  }

  return (
    <div className="relative flex min-h-full items-center justify-center overflow-hidden px-4 py-10">
      {/* Ambient background so the login screen does not feel like a void. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-70"
        style={{
          background:
            'radial-gradient(60rem 30rem at 50% -10%, color-mix(in srgb, var(--color-zulu-500) 22%, transparent), transparent 70%)',
        }}
      />

      <div className="relative w-full max-w-sm">
        <div className="mb-7 flex flex-col items-center text-center">
          <ZuluMark className="mb-3 h-12 w-12" />
          <h1 className="text-2xl font-semibold tracking-tight">
            Trade<span className="text-zulu-400">Zulu</span>
          </h1>
          <p className="mt-1 text-sm text-[var(--tz-text-muted)]">
            Your trade copier and journal. Sign in to continue.
          </p>
        </div>

        <form onSubmit={onSubmit} className="tz-card space-y-4 p-6">
          <div>
            <label className="tz-label" htmlFor="username">
              Username
            </label>
            <div className="relative">
              <User
                size={15}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--tz-text-faint)]"
              />
              <input
                id="username"
                className="tz-input pl-9"
                autoComplete="username"
                autoCapitalize="none"
                autoFocus
                required
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </div>
          </div>

          <div>
            <label className="tz-label" htmlFor="password">
              Password
            </label>
            <div className="relative">
              <KeyRound
                size={15}
                className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--tz-text-faint)]"
              />
              <input
                id="password"
                type="password"
                className="tz-input pl-9"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
          </div>

          <label className="flex cursor-pointer items-center gap-2 text-sm text-[var(--tz-text-muted)]">
            <input
              type="checkbox"
              className="size-4 accent-[var(--color-zulu-500)]"
              checked={remember}
              onChange={(event) => setRemember(event.target.checked)}
            />
            Keep me signed in
          </label>

          {error && (
            <p className="flex items-start gap-2 rounded-lg border border-loss-500/30 bg-loss-500/10 px-3 py-2 text-sm text-loss-400">
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              {error}
            </p>
          )}

          <button type="submit" className="tz-btn tz-btn-primary w-full" disabled={busy}>
            {busy && <Loader2 size={15} className="animate-spin" />}
            Sign in
          </button>
        </form>

        <p className="mt-5 text-center text-xs text-[var(--tz-text-faint)]">
          Private instance. Credentials are set with TZ_ADMIN_USER and TZ_ADMIN_PASSWORD.
        </p>
      </div>
    </div>
  )
}
