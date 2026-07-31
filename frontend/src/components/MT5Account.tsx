/**
 * The MetaTrader account form.
 *
 * Broker, trade server, account number and investor password go in here once.
 * The password is written to the server, encrypted at rest, and never sent
 * back — the form shows only whether one is stored.
 *
 * Picking a broker narrows the server list to that broker's own, which is the
 * point: MetaTrader has thousands of servers and the name has to be exact.
 * Which MetaTrader build the broker needs is deliberately not asked about —
 * that is the provisioner's business.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Loader2, Lock, Trash2 } from 'lucide-react'
import { api } from '../lib/api'
import type { BrokerList, MT5Credentials, SyncStatus, SystemInfo } from '../lib/types'
import { Button, Field } from './ui'

const OTHER = '__other__'

export function MT5Account({ status }: { status?: SyncStatus }) {
  const queryClient = useQueryClient()

  const { data: credentials } = useQuery({
    queryKey: ['mt5-credentials'],
    queryFn: () => api.get<MT5Credentials>('/mt5/credentials'),
  })
  const { data: brokerList } = useQuery({
    queryKey: ['mt5-brokers'],
    queryFn: () => api.get<BrokerList>('/mt5/brokers'),
    staleTime: 60 * 60 * 1000,
  })
  const brokers = brokerList?.brokers ?? []

  const [broker, setBroker] = useState('')
  const [server, setServer] = useState('')
  const [login, setLogin] = useState('')
  const [password, setPassword] = useState('')
  const [dirty, setDirty] = useState(false)

  // A stored server tells us the broker: it is the same string the provisioner
  // matches on, so the form reopens where it was left rather than blank.
  useEffect(() => {
    if (!credentials || dirty || brokers.length === 0) return
    setServer(credentials.server)
    setLogin(credentials.login)
    const owner = brokers.find((b) =>
      b.servers.some((s) => s.toLowerCase() === credentials.server.toLowerCase()),
    )
    setBroker(owner?.key ?? (credentials.server ? OTHER : ''))
  }, [credentials, dirty, brokers])

  const chosen = brokers.find((b) => b.key === broker)
  const servers = useMemo(() => chosen?.servers ?? [], [chosen])
  // A broker with no servers listed, or "other", means typing it. Brokers add
  // servers without telling anyone, so this is never a dead end.
  const freeText = broker === OTHER || broker === '' || servers.length === 0

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

  // Only to say how much is about to go. "Forget the stored account?" is not a
  // decision anyone can make; "delete 2,085 trades" is.
  const { data: system } = useQuery({
    queryKey: ['system'],
    queryFn: () => api.get<SystemInfo>('/settings/system'),
  })

  const forget = useMutation({
    mutationFn: () => api.delete<MT5Credentials>('/mt5/credentials'),
    onSuccess: () => {
      setBroker('')
      setServer('')
      setLogin('')
      setPassword('')
      // The journal has just lost an account: every cached figure is stale.
      void queryClient.invalidateQueries()
    },
  })

  const configured = credentials?.configured ?? false
  // A blank password means "keep the stored one", which is only sensible while
  // it is still the same account. Change the number and it is a different
  // account with a different password -- and the stored one would take the
  // terminal to a login the broker refuses, silently, forever.
  const sameAccount = !configured || login.trim() === (credentials?.login ?? '').trim()
  const needsPassword = !configured || !sameAccount
  const canSave = server.trim() && login.trim() && (password || !needsPassword)

  const track = <T,>(setter: (value: T) => void) => (value: T) => {
    setDirty(true)
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
        <Field label="Broker">
          <select
            className="tz-input"
            value={broker}
            onChange={(event) => {
              const next = event.target.value
              track(setBroker)(next)
              // Keep a typed server when moving to free text; otherwise the
              // old broker's server would be left selected under a new broker.
              const list = brokers.find((b) => b.key === next)?.servers ?? []
              setServer(list.length === 1 ? list[0] : list.includes(server) ? server : '')
            }}
          >
            <option value="">Select your broker…</option>
            {brokers.map((b) => (
              <option key={b.key} value={b.key}>
                {b.label}
              </option>
            ))}
            <option value={OTHER}>Not listed — type the server</option>
          </select>
        </Field>

        <Field
          label="Trade server"
          hint={
            freeText
              ? 'Exactly as it appears in MetaTrader under File → Open an Account.'
              : undefined
          }
        >
          {freeText ? (
            <input
              className="tz-input"
              placeholder="YourBroker-Live"
              autoComplete="off"
              value={server}
              onChange={(event) => track(setServer)(event.target.value)}
            />
          ) : (
            <select
              className="tz-input"
              value={server}
              onChange={(event) => track(setServer)(event.target.value)}
            >
              <option value="">Select a server…</option>
              {servers.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          )}
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
          hint={
            sameAccount
              ? 'The read-only password your broker issues alongside the main one. It cannot place trades, so TradeZulu physically cannot touch your account.'
              : `This is a different account from the stored ${credentials?.login ?? ''}, so it needs its own password.`
          }
        >
          <input
            type="password"
            className="tz-input"
            autoComplete="new-password"
            placeholder={
              !configured
                ? ''
                : sameAccount
                  ? '•••••••••  (stored — type to replace)'
                  : `the password for ${login.trim()}`
            }
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
        {configured && (
          <Button
            variant="danger"
            icon={<Trash2 size={15} />}
            loading={forget.isPending}
            onClick={() => {
              const stored = system?.trades ?? 0
              const warning = stored
                ? `Forget account ${credentials?.login ?? ''} and delete its ` +
                  `${stored.toLocaleString()} trades?\n\n` +
                  'Its whole history goes: trades, deals, equity samples and copy ' +
                  'activity. This cannot be undone.'
                : `Forget account ${credentials?.login ?? ''}?`
              if (confirm(warning)) forget.mutate()
            }}
          >
            Forget
          </Button>
        )}
      </div>

      {/* There is nothing to "test": saving is what starts a terminal, and the
          terminal reporting in is the only proof that matters. */}
      <TerminalState status={status} configured={configured} />
    </div>
  )
}

function TerminalState({ status, configured }: { status?: SyncStatus; configured: boolean }) {
  if (!status || !configured) return null

  if (status.phase === 'starting') {
    return (
      <p className="mt-3 flex items-start gap-1.5 text-sm text-[var(--tz-text-muted)]">
        <Loader2 size={14} className="mt-0.5 shrink-0 animate-spin" />
        {status.message || 'Starting a MetaTrader terminal for this account…'}
      </p>
    )
  }
  if (status.phase === 'connected') {
    return (
      <p className="mt-3 flex items-start gap-1.5 text-sm text-[var(--tz-gain-text)]">
        <CheckCircle2 size={14} className="mt-0.5 shrink-0" />
        Terminal running and reporting.
      </p>
    )
  }
  if (status.phase === 'stalled') {
    return (
      <p className="mt-3 flex items-start gap-1.5 text-sm text-[var(--tz-loss-text)]">
        <AlertTriangle size={14} className="mt-0.5 shrink-0" />
        {status.message}
      </p>
    )
  }
  return null
}
