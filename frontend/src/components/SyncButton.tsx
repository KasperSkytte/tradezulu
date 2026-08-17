import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, RefreshCw } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { ApiError, api } from '../lib/api'
import { relative } from '../lib/format'
import { useSettings } from '../lib/settings'
import type { SyncStatus } from '../lib/types'

interface SyncResult {
  deals_new: number
  trades_upserted: number
  message: string
}

export function SyncButton() {
  const queryClient = useQueryClient()
  const { settings } = useSettings()
  const [flash, setFlash] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const autoSyncDone = useRef(false)

  const { data: status } = useQuery({
    queryKey: ['sync-status'],
    queryFn: () => api.get<SyncStatus>('/mt5/status'),
    refetchInterval: 60_000,
  })

  const sync = useMutation({
    mutationFn: () => api.post<SyncResult>('/mt5/sync'),
    onSuccess: (result) => {
      setFlash({
        kind: 'ok',
        text: result.deals_new ? `${result.deals_new} new deal(s)` : 'Already up to date',
      })
      void queryClient.invalidateQueries()
    },
    onError: (error) => {
      setFlash({
        kind: 'error',
        text: error instanceof ApiError ? error.message : 'Sync failed',
      })
    },
  })

  useEffect(() => {
    if (!flash) return
    const timer = setTimeout(() => setFlash(null), 5000)
    return () => clearTimeout(timer)
  }, [flash])

  // Nothing is ever fetched: the terminal sends deals as they happen. This
  // only re-reads what has already arrived, so the journal is current on open.
  useEffect(() => {
    if (autoSyncDone.current) return
    if (!settings.mt5.auto_sync_on_load) return
    const lastSync = status?.last_sync_at ? new Date(status.last_sync_at).getTime() : 0
    const minInterval = (settings.mt5.auto_sync_min_interval_seconds || 120) * 1000
    if (Date.now() - lastSync < minInterval) return
    autoSyncDone.current = true
    void queryClient.invalidateQueries()
  }, [settings.mt5, status, queryClient])

  // Named after what it actually re-reads. It says nothing about the news,
  // which keeps its own copy on the server for minutes at a time -- so on that
  // page a plain "Refresh" looked broken, because pressing it could not
  // possibly have changed anything on screen.
  const title =
    settings.mt5.sync_mode === 'ea'
      ? `Re-read this account's trades and figures. The terminal sends deals as they happen, and the last arrived ${relative(status?.last_sync_at)}.`
      : "Re-read this account's trades and figures. Add your account under Settings → Accounts to sync automatically."

  return (
    <div className="flex items-center gap-2">
      {flash && (
        <span
          className={clsx(
            'tz-fade-in hidden items-center gap-1 text-xs sm:flex',
            flash.kind === 'ok' ? 'text-gain-500' : 'text-loss-500',
          )}
        >
          {flash.kind === 'ok' ? <CheckCircle2 size={13} /> : <AlertTriangle size={13} />}
          {flash.text}
        </span>
      )}
      <button
        type="button"
        title={title}
        className="tz-btn tz-btn-ghost"
        disabled={sync.isPending}
        onClick={() => {
          void queryClient.invalidateQueries()
          setFlash({ kind: 'ok', text: 'Refreshed' })
        }}
      >
        <RefreshCw size={15} className={clsx(sync.isPending && 'animate-spin')} />
        <span className="hidden sm:inline">Refresh account</span>
      </button>
    </div>
  )
}
