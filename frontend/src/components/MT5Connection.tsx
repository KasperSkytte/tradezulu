/** The MetaTrader connection, on the Accounts page where the accounts are.
 *
 *  It used to be a section of its own in Settings, which meant an account was
 *  set up in one place and listed in another, and nothing explained why. The
 *  terminal, its credentials and the account it feeds are one subject.
 */

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, Check } from 'lucide-react'
import { api } from '../lib/api'
import { money, relative } from '../lib/format'
import { useSettings } from '../lib/settings'
import type { SyncStatus, SystemInfo } from '../lib/types'
import { Card, CardHeader, Field, SegmentedControl, Toggle } from './ui'
import { MT5Account } from './MT5Account'

export function MT5Connection() {
  const { settings, save, currency } = useSettings()

  const { data: status } = useQuery({
    queryKey: ['sync-status'],
    queryFn: () => api.get<SyncStatus>('/mt5/status'),
    // Poll while a terminal is being built, so "starting" turns into "running"
    // on its own. Written once it reads as stuck rather than working.
    refetchInterval: (query) =>
      query.state.data?.phase === 'starting' || query.state.data?.phase === 'stalled'
        ? 5000
        : false,
  })
  const { data: system } = useQuery({
    queryKey: ['system'],
    queryFn: () => api.get<SystemInfo>('/settings/system'),
    staleTime: Infinity,
  })

  return (
    <Card>
      <CardHeader
        title="MetaTrader connection"
        hint="The account TradeZulu journals from. A terminal is started for it and logged in automatically; its Expert Advisor reports every deal back."
      />

      {status && (
        <div className="mb-4 grid gap-3 rounded-lg bg-[var(--tz-surface-2)] p-3 sm:grid-cols-4">
          <Fact label="Account" value={status.login && status.login !== '0' ? status.login : '—'} />
          <Fact label="Balance" value={money(status.balance, currency)} />
          <Fact label="Trades" value={String(status.total_trades)} />
          <Fact
            label="Last sync"
            value={status.last_sync_at ? relative(status.last_sync_at) : 'never'}
          />
        </div>
      )}

      <Field
        label="How deals reach TradeZulu"
        hint="A terminal is started for your account automatically and its Expert Advisor reports in. Manual import is there for history from anywhere else."
      >
        <SegmentedControl
          value={settings.mt5.sync_mode}
          onChange={(value) => void save({ mt5: { sync_mode: value } })}
          options={[
            { value: 'ea', label: 'Automatic' },
            { value: 'off', label: 'Manual import' },
          ]}
        />
      </Field>

      {settings.mt5.sync_mode === 'ea' && (
        <div className="mt-4 space-y-4">
          <MT5Account status={status} />

          <Toggle
            label="Refresh automatically while the journal is open"
            checked={settings.mt5.auto_sync_on_load}
            onChange={(value) => void save({ mt5: { auto_sync_on_load: value } })}
          />

          {status?.connected ? (
            <p className="flex items-center gap-1.5 text-sm text-[var(--tz-gain-text)]">
              <Check size={14} /> Terminal is running and logged in.
            </p>
          ) : status?.message ? (
            <p className="text-sm text-[var(--tz-text-muted)]">{status.message}</p>
          ) : null}

          {system && !system.ingest_token_configured && (
            <p className="flex items-center gap-1.5 text-sm text-[var(--tz-loss-text)]">
              <AlertTriangle size={14} /> TZ_INGEST_TOKEN is not set on the server, so the terminal
              cannot authenticate yet.
            </p>
          )}
        </div>
      )}
    </Card>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-[var(--tz-text-muted)]">{label}</p>
      <p className="tabular text-sm font-medium">{value}</p>
    </div>
  )
}
