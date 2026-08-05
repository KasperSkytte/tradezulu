/**
 * Accounts: the master, and every slave that follows it.
 *
 * The screen is built around one idea — a slave never starts copying by
 * accident. Adding one leaves it off; turning it on offers dry-run first; and
 * going live is a separate, deliberate step that says what it is about to do.
 */

import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Check,
  CircleDot,
  Copy,
  KeyRound,
  Pause,
  Play,
  Plus,
  ShieldCheck,
  Shuffle,
  Trash2,
} from 'lucide-react'
import clsx from 'clsx'
import { api, ApiError } from '../lib/api'
import { money, num, relative } from '../lib/format'
import { useSettings } from '../lib/settings'
import type { Account, CopyEvent, SlaveAccount } from '../lib/types'
import { Button, Card, CardHeader, EmptyState, ErrorState, Field, Skeleton } from '../components/ui'
import { SlaveForm } from '../components/SlaveForm'
import { CopyActivity } from '../components/CopyActivity'
import { ImportCard } from '../components/ImportCard'
import { SymbolMappings } from '../components/SymbolMappings'
import { MT5Connection } from '../components/MT5Connection'

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
  const masters = all.filter((account) => account.role === 'master')
  const slaves = all.filter((account) => account.role === 'slave')
  // Accounts that used to be the master, or that arrived with an imported
  // statement. They are kept for their history and nothing is copied from
  // them -- but they have to be removable, or they are just clutter nobody
  // can get rid of.
  const archived = all.filter(
    (account) => account.role !== 'master' && account.role !== 'slave',
  )

  return (
    <div className="space-y-5">
      <MT5Connection />

      <Card>
        <CardHeader
          title="Master account"
          hint="The account whose trades are copied. Its own history is what the journal reports on."
        />
        {masters.length ? (
          <div className="divide-y divide-[var(--tz-border)]">
            {masters.map((account) => (
              <AccountRow key={account.id} account={account} onChanged={refresh} />
            ))}
          </div>
        ) : (
          <EmptyState
            title="No master account yet"
            description="Enter its credentials above. Everything else copies from it."
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

      {archived.length > 0 && (
        <Card>
          <CardHeader
            title={`Archived accounts (${archived.length})`}
            hint="No longer the master and not copied to. Their trades still count in the journal when you pick them above, and Forget removes them for good."
          />
          <div className="divide-y divide-[var(--tz-border)]">
            {archived.map((account) => (
              <AccountRow key={account.id} account={account} onChanged={refresh} />
            ))}
          </div>
        </Card>
      )}

      <ImportCard />

      <Card>
        <CardHeader
          title="Copy activity"
          hint="Every decision the copier made, including the ones it refused and why."
        />
        <CopyActivity events={events.data ?? []} accounts={all} />
      </Card>

      <JournalAccounts />

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
  const [symbols, setSymbols] = useState(false)
  const isSlave = account.role === 'slave'
  const learnedCount = Object.keys(account.symbol_learned ?? {}).length

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
      {symbols && (
        <SymbolMappings
          account={account}
          onClose={() => setSymbols(false)}
          onChanged={onChanged}
        />
      )}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{account.name}</span>
            <StatusPill account={account} />
            <TerminalPill account={account} />
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

              <Button
                variant="ghost"
                icon={<Shuffle size={15} />}
                onClick={() => setSymbols(true)}
                title="What this broker calls each of the master's instruments"
              >
                Symbols
                {learnedCount > 0 && (
                  <span className="ml-1 text-xs text-[var(--tz-text-faint)]">{learnedCount}</span>
                )}
              </Button>

              {onEdit && (
                <Button variant="ghost" onClick={onEdit}>
                  Settings
                </Button>
              )}
            </>
          )}

          <Button
            variant="ghost"
            icon={<Trash2 size={15} />}
            loading={remove.isPending}
            onClick={() => {
              const what =
                account.role === 'master'
                  ? `Forget ${account.name} (${account.login})?\n\n` +
                    'Its stored credentials go too, so no terminal is started for it ' +
                    'again.'
                  : `Remove ${account.name} (${account.login})?`
              if (
                window.confirm(
                  `${what}\n\nIts whole history goes with it: trades, equity samples ` +
                    'and copy activity. This cannot be undone.',
                )
              )
                remove.mutate()
            }}
            title={account.role === 'master' ? 'Forget this account' : 'Remove this account'}
          >
            {account.role === 'master' ? 'Forget' : <span className="sr-only">Remove</span>}
          </Button>
        </div>
      </div>
    </div>
  )
}

/** Whether this account's terminal is up, on the account it belongs to.
 *
 *  It used to be stated twice on this page and tied to neither -- once under
 *  the credentials form and once inside it -- which was readable enough with
 *  one account and says nothing useful with three. A terminal reporting in is
 *  the only evidence any of this works, so it belongs next to the account it
 *  is evidence about.
 */
function TerminalPill({ account }: { account: SlaveAccount }) {
  const seen = account.last_sync_at ? new Date(account.last_sync_at).getTime() : 0
  if (!seen) {
    return (
      <Pill className="text-[var(--tz-text-muted)]" title="No terminal has reported for this account yet">
        <CircleDot size={11} /> no terminal yet
      </Pill>
    )
  }
  // A master polls every ten seconds and a slave every two, so a minute of
  // silence is already unusual and two is something to look at.
  const quietFor = Date.now() - seen
  if (quietFor < 2 * 60 * 1000) {
    return (
      <Pill className="border-gain-500/40 bg-gain-500/10 text-gain-400" title="Its Expert Advisor is reporting in">
        <Check size={11} /> terminal up
      </Pill>
    )
  }
  return (
    <Pill className="border-loss-500/40 bg-loss-500/10 text-loss-400" title="Its Expert Advisor has stopped reporting">
      <AlertTriangle size={11} /> quiet {relative(account.last_sync_at)}
    </Pill>
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

function Pill({
  children,
  className,
  title,
}: {
  children: React.ReactNode
  className?: string
  title?: string
}) {
  return (
    <span
      title={title}
      className={clsx(
        'inline-flex items-center gap-1 rounded-full border border-[var(--tz-border)] px-2 py-0.5 text-xs',
        className,
      )}
    >
      {children}
    </span>
  )
}

/* --------------------------------------------------------------------- */

function JournalAccounts() {
  const queryClient = useQueryClient()
  const { currency } = useSettings()
  const { data: accounts = [], isLoading } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => api.get<Account[]>('/accounts'),
  })

  const update = useMutation({
    mutationFn: ({ id, patch }: { id: number; patch: Partial<Account> }) =>
      api.patch<Account>(`/accounts/${id}`, patch),
    onSuccess: () => void queryClient.invalidateQueries(),
  })

  if (isLoading) return <Skeleton className="h-48" />

  return (
    <div className="space-y-4">
      {accounts.map((account) => (
        <Card key={account.id}>
          <CardHeader
            title={account.name || `Account ${account.login}`}
            action={
              account.is_default ? (
                <span className="tz-chip bg-zulu-500/15 text-zulu-400">Default</span>
              ) : (
                <Button onClick={() => update.mutate({ id: account.id, patch: { is_default: true } })}>
                  Make default
                </Button>
              )
            }
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Display name">
              <input
                className="tz-input"
                defaultValue={account.name}
                onBlur={(event) =>
                  update.mutate({ id: account.id, patch: { name: event.target.value } })
                }
              />
            </Field>
            <Field
              label={`Starting balance (${currency})`}
              hint="The deposit this account began with. Drawdown percentages and percentage risk are measured against it."
            >
              <NumberField
                value={account.initial_balance}
                step={100}
                onCommit={(value) =>
                  update.mutate({ id: account.id, patch: { initial_balance: value } })
                }
              />
            </Field>
          </div>
          <dl className="mt-4 space-y-1.5 border-t border-[var(--tz-border)] pt-3 text-sm">
            <Fact inline label="Login" value={account.login} />
            <Fact inline label="Broker" value={account.broker || '—'} />
            <Fact inline label="Server" value={account.server || '—'} />
            <Fact inline label="Currency" value={account.currency} />
            <Fact inline label="Leverage" value={account.leverage ? `1:${account.leverage}` : '—'} />
            <Fact inline label="Balance" value={num(account.balance, 2)} />
          </dl>
        </Card>
      ))}
    </div>
  )
}

function Fact({
  label,
  value,
  inline,
}: {
  label: string
  value: string
  inline?: boolean
}) {
  if (inline) {
    return (
      <div className="flex justify-between gap-3">
        <dt className="text-[var(--tz-text-muted)]">{label}</dt>
        <dd className="truncate font-medium">{value}</dd>
      </div>
    )
  }
  return (
    <div>
      <p className="text-xs text-[var(--tz-text-muted)]">{label}</p>
      <p className="tabular mt-0.5 font-semibold">{value}</p>
    </div>
  )
}

function NumberField({
  value,
  step,
  disabled,
  onCommit,
}: {
  value: number
  step: number
  disabled?: boolean
  onCommit: (value: number) => void
}) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => setDraft(String(value)), [value])

  return (
    <input
      type="number"
      step={step}
      disabled={disabled}
      className="tz-input disabled:opacity-50"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => {
        const parsed = Number(draft)
        if (Number.isFinite(parsed) && parsed !== value) onCommit(parsed)
        else setDraft(String(value))
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter') event.currentTarget.blur()
      }}
    />
  )
}
