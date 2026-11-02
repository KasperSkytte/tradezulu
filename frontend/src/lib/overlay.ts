import { useEffect, useRef, useState } from 'react'
import type { MouseEvent, PointerEvent } from 'react'

/** Escape, the scroll lock, and a backdrop that only closes on a real click.
 *
 *  Every overlay here wants the same three things, and they had been written
 *  twice and differently: the shared dialog closed on Escape and the account
 *  form did not, so the same key did different things depending on which popup
 *  was open.
 *
 *  The backdrop is the part worth explaining. Closing on a click that merely
 *  *ended* on the backdrop throws away a half-filled form on an ordinary
 *  gesture -- select the text in a field, drag a few pixels past the edge of
 *  the card, release, and it is gone. The browser fires a single click at the
 *  nearest common ancestor of where the press began and where it ended, which
 *  for that drag is the backdrop itself. Nothing inside the card is on that
 *  event's path, so the usual trick of stopping propagation on the card cannot
 *  help: the card never hears about it. The press and the release both have to
 *  land on the backdrop for it to count as a click outside.
 *
 *  ``dismissable`` is the second half of it. A popup that can be dismissed by
 *  a stray click is fine when it only shows something and costs a reopen; it
 *  is not fine when it holds typing, where the cost is doing it all again. A
 *  form passes false once it has been touched, which leaves Escape and the
 *  backdrop working right up until there is something to lose, and leaves the
 *  explicit close control -- which is never ambiguous -- always working.
 */
export function useOverlay(onClose: () => void, dismissable = true) {
  useEffect(() => {
    if (!dismissable) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose, dismissable])

  // Separate from the key handler: the page underneath must stay still for as
  // long as the overlay is up, whether or not it can be dismissed.
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  const pressedOutside = useRef(false)

  return {
    onPointerDown: (event: PointerEvent) => {
      pressedOutside.current = event.target === event.currentTarget
    },
    onClick: (event: MouseEvent) => {
      if (!dismissable || !pressedOutside.current) return
      if (event.target !== event.currentTarget) return
      pressedOutside.current = false
      onClose()
    },
  }
}

/** Whether a form has been touched since it opened.
 *
 *  Passed straight to {@link useOverlay} so an untouched form stays cheap to
 *  dismiss and a filled one cannot be lost to a stray click. The snapshot is
 *  taken once, on mount, which is why the values arrive already assembled:
 *  what matters is the difference from how it opened, not from how it is
 *  stored.
 */
export function useDirty(values: object): boolean {
  const current = JSON.stringify(values)
  const [opened] = useState(current)
  return current !== opened
}
