/**
 * A "now" that moves, for the few places that draw where the present is.
 *
 * Anything showing an age has to re-render for that age to mean anything: a
 * page left open otherwise says "4 min ago" about a story from an hour back,
 * and looks broken in a way that is hard to argue with. Half a minute is
 * enough — nothing here is written to the second.
 */

import { useEffect, useState } from 'react'

export function useNow(active = true, everyMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    const timer = window.setInterval(() => setNow(Date.now()), everyMs)
    return () => window.clearInterval(timer)
  }, [active, everyMs])
  return now
}
