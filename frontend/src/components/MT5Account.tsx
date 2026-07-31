/**
 * The MetaTrader account form.
 *
 * Server, account number and investor password go in here once. The password
 * is written to the server, encrypted at rest, and never sent back — the form
 * shows only whether one is stored.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { AlertTriangle, CheckCircle2, KeyRound, Lock, Trash2, Zap } from 'lucide-react'
import { ApiError, api } from '../lib/api'
import { money } from '../lib/format'
import type { MT5ConnectResult, MT5Credentials, SyncStatus } from '../lib/types'
import { Button, Field } from './ui'

export function MT5Account({ status }: { status?: SyncStatus }) {
  const queryClient = useQueryClient()

  const { data: credentials } = useQuery({
    queryKey: ['mt5-credentials'],
    queryFn: () => api.get<MT5Credentials>('/mt5/credentials'),
  })

  const [server, setServer] = useState('')
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [dirty, setDirty] = useState(false)
  const [result, setResult] = useState<
    { kind: 'ok' | 'error'; text: string; detail?: string } | null
  >(null)

  useEffect(() => {
    if (!credentials || dirty) return
    setServer(credentials.server)
    setLogin(credentials.login)
  }, [credentials, dirty])

  const save = useMutation({
    mutationFn: () =>
      api.put<MT5Credentials>('/mt5/credentials', {
        server: server.trim(),
        login: login.trim(),
        // Undefined leaves the stored password untouched.
        password: password ? password : undefined,
      }),
    onSuccess: () => {
      setPassword('')
      setDirty(false)
      void queryClient.invalidateQueries({ queryKey: ['mt5-credentials'] })
      void queryClient.invalidateQueries({ queryKey: ['sync-status'] })
    },
  })

  const connect = useMutation({
    mutationFn: () => api.post<MT5ConnectResult>('/mt5/connect'),
    onSuccess: (body) => {
      const account = body.account
      setResult({
        kind: 'ok',
        text: account
          ? `Connected to ${account.company || account.server} as ${account.login}`
          : 'Connected',
        detail: account
          ? `Balance ${money(account.balance, '')} ${account.currency}` +
            (account.trade_allowed
              ? ' · this login can trade — consider using the investor password instead'
              : ' · read-only investor login')
          : undefined,
      })
      void queryClient.invalidateQueries({ queryKey: ['sync-status'] })
      void queryClient.invalidateQueries({ queryKey: ['accounts'] })
    },
    onError: (error) =>
      setResult({
        kind: 'error',
        text: error instanceof ApiError ? error.message : 'Could not connect',
      }),
  })

  const forget = useMutation({
    mutationFn: () => api.delete<MT5Credentials>('/mt5/credentials'),
    onSuccess: () => {
      setServer('')
      setLogin('')
      setPassword('')
      setResult(null)
      void queryClient.invalidateQueries({ queryKey: ['mt5-credentials'] })
      void queryClient.invalidateQueries({ queryKey: ['sync-status'] })
    },
  })

  const configured = credentials?.configured ?? false
  const canSave = server.trim() && login.trim() && (password || configured)

  const track = <T,>(setter: (value: T) => void) => (value: T) => {
    setDirty(true)
    setResult(null)
    setter(value)
  }

  return (
    <div className="rounded-lg border border-[var(--tz-border)] bg-[var(--tz-surface-2)] p-4">
      <div className="mb-3 flex items-center gap-2">
        <Lock size={15} className="text-[var(--tz-text-muted)]" />
        <p className="text-sm font-medium">Your MetaTrader account</p>
        {configured && (
          <span className="tz-chip bg-gain-500/15 text-[var(--tz-gain-text)]">Stored</span>
        )}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field
          label="Trade server"
          hint="Exactly as it appears in MetaTrader under File → Open an Account, e.g. ICMarketsSC-Live12."
        >
          <input
            className="tz-input"
            placeholder="YourBroker-Live"
            autoComplete="off"
            value={server}
            onChange={(event) => track(setServer)(event.target.value)}
          />
        </Field>

        <Field label="Account number">
          <input
            className="tz-input"
            placeholder="5000123"
            inputMode="numeric"
            autoComplete="off"
            value={login}
            onChange={(event) => track(setLogin)(event.target.value)}
          />
        </Field>

        <Field
          label="Investor password"
          hint="The read-only password your broker issues alongside the main one. It cannot place trades, so TradeZulu physically cannot touch your account."
          className="sm:col-span-2"
        >
          <input
            type="password"
            className="tz-input"
            autoComplete="new-password"
            placeholder={configured ? '•••••••••  (stored — type to replace)' : ''}
            value={password}
            onChange={(event) => track(setPassword)(event.target.value)}
          />
        </Field>
      </div>

      {credentials && configured && !credentials.password_readable && (
        <p className="mt-3 flex items-start gap-1.5 text-sm text-[var(--tz-loss-text)]">
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          The stored password can no longer be decrypted — TZ_SECRET_KEY has changed since it was
          saved. Enter it again.
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <Button
          variant="primary"
          disabled={!canSave}
          loading={save.isPending}
          onClick={() => save.mutate()}
        >
          {configured ? 'Update account' : 'Save account'}
        </Button>
        <Button
          icon={<Zap size={15} />}
          disabled={!configured || save.isPending}
          loading={connect.isPending}
          onClick={() => {
            setResult(null)
            connect.mutate()
          }}
        >
          Test connection
        </Button>
        {configured && (
          <Button
            variant="danger"
            icon={<Trash2 size={15} />}
            loading={forget.isPending}
            onClick={() => {
              if (confirm('Forget the stored MetaTrader account?')) forget.mutate()
            }}
          >
            Forget
          </Button>
        )}
      </div>

      {result && (
        <div
          className={`mt-3 flex items-start gap-1.5 text-sm ${
            result.kind === 'ok' ? 'text-[var(--tz-gain-text)]' : 'text-[var(--tz-loss-text)]'
          }`}
        >
          {result.kind === 'ok' ? (
            <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
          ) : (
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
          )}
          <span>
            {result.text}
            {result.detail && (
              <span className="mt-0.5 block text-xs text-[var(--tz-text-muted)]">
                {result.detail}
              </span>
            )}
          </span>
        </div>
      )}

      {status && status.connected === false && (
        <p className="mt-3 flex items-start gap-1.5 text-sm text-[var(--tz-text-muted)]">
          <KeyRound size={14} className="mt-0.5 shrink-0" />
          No terminal has reported in yet. One is started for this account automatically,
          usually within a minute.
        </p>
      )}
    </div>
  )
}
