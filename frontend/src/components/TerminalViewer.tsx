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
 * Watching and driving are different sockets rather than a setting on one. The
 * provisioner runs two VNC servers on each display, one of them view-only, and
 * a viewer that has not asked for control is connected to that one -- so a
 * click cannot reach the terminal even if this file is wrong about everything.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { Hand, Monitor, RefreshCw, X } from 'lucide-react'
import RFB from '@novnc/novnc'
import { api } from '../lib/api'
import { Button } from './ui'

type Viewable = {
  account_id: number
  login: string
  available: boolean
  can_control: boolean
  phase: string
  message_phase: string
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
  const panel = useRef<HTMLDivElement>(null)
  const [status, setStatus] = useState<Status>('asking')
  const [message, setMessage] = useState('')
  const [phaseNote, setPhaseNote] = useState('')
  const [canControl, setCanControl] = useState(false)
  const [control, setControl] = useState(false)

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
      setCanControl(info.can_control)
      // An empty display is black, and black with nothing said over it reads
      // as a broken viewer rather than as a terminal that has not been built
      // yet. Kept beside the picture, not instead of it: the screen is still
      // shown, in case there is something on it after all.
      setPhaseNote(info.message_phase)
      if (!info.available) {
        setStatus('unavailable')
        setMessage(info.message)
        return
      }

      setStatus('connecting')
      const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const url =
        `${scheme}://${window.location.host}/api/terminal/${accountId}/stream` +
        (control ? '?control=true' : '')
      rfb = new RFB(screen.current!, url, { wsProtocols: ['binary'] })
      // The terminal's display is 1400x1000 and the panel is not, so the
      // picture is scaled to fit whatever size the panel has been dragged to.
      rfb.scaleViewport = true
      rfb.clipViewport = false
      rfb.viewOnly = !control
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
    // Control is part of this: taking it means a different socket, to the
    // server on the display that accepts input, so the session is remade.
  }, [accountId, control])

  // noVNC rescales its canvas when the *window* resizes, and the panel here
  // resizes on its own. Telling it the window changed is what its own handler
  // listens for, and is cheaper than reaching into its internals.
  useEffect(() => {
    const element = panel.current
    if (!element || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => window.dispatchEvent(new Event('resize')))
    observer.observe(element)
    return () => observer.disconnect()
  }, [])

  const takeControl = useCallback(() => {
    if (control) {
      setControl(false)
      return
    }
    const ok = window.confirm(
      `Take control of the terminal for ${login}?\n\n` +
        'This is the real MetaTrader, logged into the real account. A click ' +
        'can place, modify or close an order, and nothing here asks twice ' +
        'before it does.\n\n' +
        'The provisioner may also be driving this terminal at the same moment ' +
        '— if it is part-way through a dialog, your clicks and its clicks land ' +
        'on the same window.',
    )
    if (ok) setControl(true)
  }, [control, login])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      {/* Resizable by dragging the corner, and sized in viewport units to
          start with so it is usable on a laptop and on a large screen without
          either being the one it was designed for. */}
      <div
        ref={panel}
        style={{ resize: 'both' }}
        className="flex h-[75vh] max-h-full w-[min(72rem,100%)] min-w-[24rem] flex-col overflow-hidden rounded-xl border border-[var(--tz-border)] bg-[var(--tz-surface)]"
      >
        <header className="flex shrink-0 items-center gap-3 border-b border-[var(--tz-border)] px-4 py-3">
          <Monitor size={16} className="text-[var(--tz-text-muted)]" />
          <div>
            <h2 className="text-sm font-semibold text-[var(--tz-text)]">Terminal for {login}</h2>
            <p className="text-xs text-[var(--tz-text-muted)]">
              {status !== 'watching'
                ? 'Not connected'
                : control
                  ? 'Live — your keyboard and mouse reach this terminal'
                  : 'Live, view only'}
            </p>
          </div>

          <div className="ml-auto flex items-center gap-2">
            {canControl && (
              <Button
                variant={control ? 'danger' : 'ghost'}
                icon={<Hand size={14} />}
                onClick={takeControl}
              >
                {control ? 'Give up control' : 'Take control'}
              </Button>
            )}
            <button
              onClick={onClose}
              aria-label="Close"
              className="rounded-md p-1.5 text-[var(--tz-text-muted)] hover:bg-[var(--tz-surface-raised)] hover:text-[var(--tz-text)]"
            >
              <X size={18} />
            </button>
          </div>
        </header>

        {control && status === 'watching' && (
          <p className="shrink-0 border-b border-[var(--tz-border)] bg-[var(--tz-loss)]/10 px-4 py-2 text-xs text-[var(--tz-loss)]">
            You are driving a live terminal. A click here can place or close a real order.
          </p>
        )}

        {/* A definite height, not a percentage of one. noVNC scales its canvas
            to the element it is given, and h-full inside a flex column with no
            resolved height is 0 -- which drew the screen perfectly, at zero by
            zero pixels, and looked exactly like a black screen. */}
        <div className="relative min-h-0 flex-1 bg-black">
          <div ref={screen} className="absolute inset-0" />
          {(status !== 'watching' || phaseNote) && (
            <div className="pointer-events-none absolute inset-x-0 bottom-0 flex flex-col items-center gap-2 p-6 text-center">
              {status === 'connecting' || status === 'asking' ? (
                <RefreshCw size={20} className="animate-spin text-[var(--tz-text-muted)]" />
              ) : null}
              <p className="max-w-md rounded-md bg-black/70 px-3 py-2 text-sm text-[var(--tz-text-muted)]">
                {status === 'asking' && 'Looking for this terminal…'}
                {status === 'connecting' && 'Connecting to its screen…'}
                {(status === 'unavailable' || status === 'lost') && message}
                {status === 'watching' && phaseNote}
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
