/**
 * Accounts: the master, and every slave that follows it.
 *
 * The screen is built around one idea — a slave never starts copying by
 * accident. Adding one leaves it off; turning it on offers dry-run first; and
 * going live is a separate, deliberate step that says what it is about to do.
 */

import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CircleDot,
  Copy,
  KeyRound,
  Pause,
  Play,
  Plus,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import clsx from 'clsx'
import { api, ApiError } from '../lib/api'
import { money } from '../lib/format'
import type { CopyEvent, SlaveAccount } from '../lib/types'
import { Button, Card, CardHeader, EmptyState, ErrorState, Skeleton } from '../components/ui'
import { SlaveForm } from '../components/SlaveForm'
import { CopyActivity } from '../components/CopyActivity'

export function AccountsPage() {
  const queryClient = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [editing, setEditing] = useState<SlaveAccount | null>(null)

  const accounts = useQuery({
    queryKey: ['accounts'],
    queryFn: () => api.get<SlaveAccount[]>('/accounts'),
    refetchInterval: 15_000,
  })

  const events = useQuery({
    queryKey: ['copy-events'],
    queryFn: () => api.get<CopyEvent[]>('/accounts/events/recent', { limit: 60 }),
    refetchInterval: 10_000,
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['accounts'] })
    void queryClient.invalidateQueries({ queryKey: ['copy-events'] })
  }

  if (accounts.isLoading) return <Skeleton className="h-64 w-full" />
  if (accounts.isError) return <ErrorState error={accounts.error} retry={() => accounts.refetch()} />

  const all = accounts.data ?? []
  const master = all.find((account) => account.role === 'master')
  const slaves = all.filter((account) => account.role === 'slave')

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Master account"
          hint="The account whose trades are copied. Its own history is what the journal reports on."
        />
        {master ? (
          <AccountRow account={master} onChanged={refresh} />
        ) : (
          <EmptyState
            title="No master account yet"
            description="Connect one in Settings → MetaTrader 5. Everything else copies from it."
          />
        )}
      </Card>

      <Card>
        <CardHeader
          title={`Slave accounts${slaves.length ? ` (${slaves.length})` : ''}`}
          hint="Each one follows the master under its own sizing and risk rules."
          action={
            <Button onClick={() => setAdding(true)} icon={<Plus size={15} />}>
              Add a slave account
            </Button>
          }
        />

        {slaves.length === 0 && !adding ? (
          <EmptyState
            title="No slave accounts"
            description="Add one and it will mirror the master's trades — scaled to its own size, under its own limits. Nothing is copied for real until you arm it."
          />
        ) : (
          <div className="divide-y divide-[var(--tz-border)]">
            {slaves.map((account) => (
              <AccountRow
                key={account.id}
                account={account}
                onChanged={refresh}
                onEdit={() => setEditing(account)}
              />
            ))}
          </div>
        )}
      </Card>

      <Card>
        <CardHeader
          title="Copy activity"
          hint="Every decision the copier made, including the ones it refused and why."
        />
        <CopyActivity events={events.data ?? []} accounts={all} />
      </Card>

      {(adding || editing) && (
        <SlaveForm
          account={editing}
          onClose={() => {
            setAdding(false)
            setEditing(null)
          }}
          onSaved={() => {
            setAdding(false)
            setEditing(null)
            refresh()
          }}
        />
      )}
    </div>
  )
}

function AccountRow({
  account,
  onChanged,
  onEdit,
}: {
  account: SlaveAccount
  onChanged: () => void
  onEdit?: () => void
}) {
  const [error, setError] = useState<string | null>(null)
  const isSlave = account.role === 'slave'

  const arm = useMutation({
    mutationFn: (body: { enabled: boolean; dry_run: boolean }) =>
      api.post(`/accounts/${account.id}/arm`, body),
    onSuccess: () => {
      setError(null)
      onChanged()
    },
    onError: (caught) =>
      setError(caught instanceof ApiError ? caught.message : 'Could not change that'),
  })

  const resume = useMutation({
    mutationFn: () => api.post(`/accounts/${account.id}/resume`, {}),
    onSuccess: onChanged,
  })

  const remove = useMutation({
    mutationFn: () => api.delete(`/accounts/${account.id}`),
    onSuccess: onChanged,
  })

  return (
    <div className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{account.name}</span>
            <StatusPill account={account} />
            {isSlave && !account.has_password && (
              <span
                className="inline-flex items-center gap-1 rounded-full border border-[var(--tz-border)] px-2 py-0.5 text-xs text-[var(--tz-text-muted)]"
                title="Without a trade-enabled password this account cannot place orders"
              >
                <KeyRound size={11} /> no password
              </span>
            )}
          </div>
          <p className="mt-1 text-sm text-[var(--tz-text-muted)]">
            {account.login} · {account.server || 'no server'}
            {account.broker ? ` · ${account.broker}` : ''}
            {account.open_copies > 0 ? ` · ${account.open_copies} open` : ''}
          </p>
          {account.copy_halted && account.copy_halt_reason && (
            <p className="mt-2 flex items-start gap-2 rounded-lg border border-loss-500/30 bg-loss-500/10 px-3 py-2 text-sm text-loss-400">
              <AlertTriangle size={15} className="mt-0.5 shrink-0" />
              <span>
                Halted: {account.copy_halt_reason}
                <button
                  className="ml-2 underline underline-offset-2"
                  onClick={() => resume.mutate()}
                >
                  clear
                </button>
              </span>
            </p>
          )}
          {error && <p className="mt-2 text-sm text-loss-400">{error}</p>}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="text-right">
            <div className="tabular text-sm font-medium">
              {money(account.equity, account.currency)}
            </div>
            <div className="text-xs text-[var(--tz-text-faint)]">equity</div>
          </div>

          {isSlave && (
            <>
              {account.copy_enabled ? (
                <Button
                  variant="ghost"
                  icon={<Pause size={15} />}
                  onClick={() => arm.mutate({ enabled: false, dry_run: account.copy_dry_run })}
                >
                  Stop
                </Button>
              ) : (
                <Button
                  variant="ghost"
                  icon={<Play size={15} />}
                  onClick={() => arm.mutate({ enabled: true, dry_run: true })}
                  title="Start in dry-run: it records what it would have done, without trading"
                >
                  Start dry-run
                </Button>
              )}

              {account.copy_enabled && account.copy_dry_run && (
                <Button
                  icon={<ShieldCheck size={15} />}
                  onClick={() => {
                    const ok = window.confirm(
                      `Take ${account.name} live?\n\nFrom now on it will place real orders on ` +
                        `account ${account.login} whenever the master trades, using the ` +
                        `password you stored.`,
                    )
                    if (ok) arm.mutate({ enabled: true, dry_run: false })
                  }}
                >
                  Go live
                </Button>
              )}

              {onEdit && (
                <Button variant="ghost" onClick={onEdit}>
                  Settings
                </Button>
              )}
              <Button
                variant="ghost"
                icon={<Trash2 size={15} />}
                onClick={() => {
                  if (window.confirm(`Remove ${account.name}? Its copy history goes with it.`))
                    remove.mutate()
                }}
                title="Remove this account"
              >
                <span className="sr-only">Remove</span>
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

function StatusPill({ account }: { account: SlaveAccount }) {
  if (account.role === 'master') {
    return (
      <Pill className="border-zulu-500/40 bg-zulu-500/10 text-zulu-400">
        <Copy size={11} /> master
      </Pill>
    )
  }
  if (account.copy_halted) {
    return (
      <Pill className="border-loss-500/40 bg-loss-500/10 text-loss-400">
        <AlertTriangle size={11} /> halted
      </Pill>
    )
  }
  if (!account.copy_enabled) {
    return <Pill className="text-[var(--tz-text-muted)]">off</Pill>
  }
  if (account.copy_dry_run) {
    return (
      <Pill className="border-[#eab308]/40 bg-[#eab308]/10 text-[#eab308]">
        <CircleDot size={11} /> dry run
      </Pill>
    )
  }
  return (
    <Pill className="border-gain-500/40 bg-gain-500/10 text-gain-400">
      <CircleDot size={11} /> live
    </Pill>
  )
}

function Pill({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-full border border-[var(--tz-border)] px-2 py-0.5 text-xs',
        className,
      )}
    >
      {children}
    </span>
  )
}
