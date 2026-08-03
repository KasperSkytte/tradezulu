/** The master account's credentials, on the Accounts page.
 *
 *  It used to be a section of its own in Settings, which meant an account was
 *  set up in one place and listed in another, and nothing explained why. The
 *  terminal, its credentials and the account it feeds are one subject.
 *
 *  It is only ever about the master. Slaves are added below with their own
 *  credentials, and calling this "MetaTrader connection" implied it was where
 *  every terminal came from -- so the natural reading of Forget, which used to
 *  sit here, was "disconnect MetaTrader" rather than "delete this account and
 *  its history". Forgetting now lives on the account card itself.
 */

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { api } from '../lib/api'
import { money, relative } from '../lib/format'
import { useSettings } from '../lib/settings'
import type { SyncStatus, SystemInfo } from '../lib/types'
import { Card, CardHeader, Field, SegmentedControl, Toggle } from './ui'
import { MT5Account } from './MT5Account'

//: Monday first, matching Python's weekday numbering on the provisioner side.
const DAYS = [
  'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday',
]

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
        title="Master account credentials"
        hint="The one account TradeZulu trades from: its deals are the journal, and every slave copies them. A terminal is started for it and logged in automatically; its Expert Advisor reports each deal back. Slaves are added further down and keep their own credentials."
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
        label="How the master's deals reach TradeZulu"
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

          {/* MetaTrader installs its own updates on restart, so the terminals
              are cycled weekly at a quiet hour rather than a broker's new build
              stopping one mid-week behind a dialog nobody is there to answer. */}
          <div className="grid gap-4 border-t border-[var(--tz-border)] pt-4 sm:grid-cols-2">
            <Field
              label="Restart terminals on"
              hint="MetaTrader applies its updates when it restarts. Pick an hour you are not trading."
            >
              <select
                className="tz-input"
                value={String(settings.mt5.restart_weekday ?? 6)}
                onChange={(event) =>
                  void save({ mt5: { restart_weekday: Number(event.target.value) } })
                }
              >
                {DAYS.map((day, index) => (
                  <option key={day} value={String(index)}>
                    {day}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="At">
              <select
                className="tz-input"
                value={String(settings.mt5.restart_hour ?? 3)}
                onChange={(event) =>
                  void save({ mt5: { restart_hour: Number(event.target.value) } })
                }
              >
                {Array.from({ length: 24 }, (_, hour) => (
                  <option key={hour} value={String(hour)}>
                    {String(hour).padStart(2, '0')}:00
                  </option>
                ))}
              </select>
            </Field>
          </div>

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
