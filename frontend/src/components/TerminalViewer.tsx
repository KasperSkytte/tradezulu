/**
 * One account's MetaTrader terminal, on screen.
 *
 * The terminals run on virtual displays on the host that nobody has a monitor
 * for. Seeing one used to mean an SSH tunnel and a VNC viewer; this draws the
 * same pixels into a canvas on the page.
 *
 * One account per viewer, because the display underneath it holds one
 * account's terminal and nothing else. That is where the isolation lives --
 * not in this component, which could not leak another account's screen if it
 * tried, because those pixels are not on the display it is connected to.
 *
 * Read-only. The VNC server is started with -viewonly, so the keyboard and
 * mouse are not merely ignored here: they are refused at the far end, where a
 * stray click would be an order on a live account.
 */

import { useEffect, useRef, useState } from 'react'
import { Monitor, RefreshCw, X } from 'lucide-react'
import RFB from '@novnc/novnc'
import { api } from '../lib/api'
import { Button } from './ui'

type Viewable = {
  account_id: number
  login: string
  available: boolean
  phase: string
  display: string
  message: string
}

type Status = 'asking' | 'connecting' | 'watching' | 'unavailable' | 'lost'

export function TerminalViewer({
  accountId,
  login,
  onClose,
}: {
  accountId: number
  login: string
  onClose: () => void
}) {
  const screen = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<Status>('asking')
  const [message, setMessage] = useState('')

  useEffect(() => {
    let rfb: RFB | null = null
    let dropped = false

    const start = async () => {
      // Asked before the socket is opened, so a terminal that is still
      // installing gets a sentence rather than a failed connection.
      let info: Viewable
      try {
        info = await api.get<Viewable>(`/terminal/${accountId}`)
      } catch {
        if (!dropped) {
          setStatus('unavailable')
          setMessage('Could not ask the server about this terminal.')
        }
        return
      }
      if (dropped) return
      if (!info.available) {
        setStatus('unavailable')
        setMessage(info.message)
        return
      }

      setStatus('connecting')
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const url = `${scheme}://${window.location.host}/api/terminal/${accountId}/stream`
      rfb = new RFB(screen.current!, url, { wsProtocols: ['binary'] })
      // The terminal's display is 1400x1000 and the card is not, so the
      // picture is scaled to fit rather than cropped or scrolled.
      rfb.scaleViewport = true
      rfb.clipViewport = false
      rfb.viewOnly = true
      rfb.addEventListener('connect', () => !dropped && setStatus('watching'))
      rfb.addEventListener('disconnect', () => {
        if (dropped) return
        setStatus('lost')
        setMessage('The connection to this terminal ended.')
      })
    }

    void start()
    return () => {
      dropped = true
      // Disconnect on the way out, or the relay -- and the x11vnc behind it --
      // is left holding a client that nobody is looking at.
      rfb?.disconnect()
    }
  }, [accountId])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="flex max-h-full w-full max-w-5xl flex-col overflow-hidden rounded-xl border border-[var(--tz-border)] bg-[var(--tz-surface)]">
        <header className="flex items-center gap-3 border-b border-[var(--tz-border)] px-4 py-3">
          <Monitor size={16} className="text-[var(--tz-text-muted)]" />
          <div>
            <h2 className="text-sm font-semibold text-[var(--tz-text)]">
              Terminal for {login}
            </h2>
            <p className="text-xs text-[var(--tz-text-muted)]">
              {status === 'watching' ? 'Live, view only' : 'Not connected'}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="ml-auto rounded-md p-1.5 text-[var(--tz-text-muted)] hover:bg-[var(--tz-surface-raised)] hover:text-[var(--tz-text)]"
          >
            <X size={18} />
          </button>
        </header>

        <div className="relative min-h-[320px] flex-1 bg-black">
          <div ref={screen} className="h-full w-full [&>div]:h-full [&>div]:w-full" />
          {status !== 'watching' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center">
              {status === 'connecting' || status === 'asking' ? (
                <RefreshCw size={20} className="animate-spin text-[var(--tz-text-muted)]" />
              ) : null}
              <p className="max-w-md text-sm text-[var(--tz-text-muted)]">
                {status === 'asking' && 'Looking for this terminal…'}
                {status === 'connecting' && 'Connecting to its screen…'}
                {(status === 'unavailable' || status === 'lost') && message}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/** The two things you can do to a terminal from the accounts page. */
export function TerminalControls({ accountId, login }: { accountId: number; login: string }) {
  const [watching, setWatching] = useState(false)
  const [restarting, setRestarting] = useState(false)
  const [note, setNote] = useState('')

  const restart = async () => {
    setRestarting(true)
    try {
      await api.post(`/terminal/${accountId}/restart`, {})
      // Asked for, not done: the provisioner carries it out on its next pass,
      // and saying "restarted" here would be a claim about something that has
      // not happened yet.
      setNote('Restart requested. It stops within a minute and comes back on its own.')
    } catch {
      setNote('Could not ask for a restart.')
    } finally {
      setRestarting(false)
    }
  }

  return (
    <>
      <Button variant="ghost" icon={<Monitor size={14} />} onClick={() => setWatching(true)}>
        Inspect
      </Button>
      <Button
        variant="ghost"
        icon={<RefreshCw size={14} className={restarting ? 'animate-spin' : ''} />}
        onClick={() => void restart()}
        disabled={restarting}
      >
        Restart
      </Button>
      {note && <span className="text-xs text-[var(--tz-text-muted)]">{note}</span>}
      {watching && (
        <TerminalViewer accountId={accountId} login={login} onClose={() => setWatching(false)} />
      )}
    </>
  )
}
