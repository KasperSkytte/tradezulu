/** The week's releases, from ForexFactory's own feed.
 *
 *  Not an embed: ForexFactory sits behind a Cloudflare challenge and sends
 *  X-Frame-Options: SAMEORIGIN, so an iframe of it shows a 403 page. The
 *  server reads their published JSON instead and this draws it, which also
 *  means it matches the rest of the journal rather than being a rectangle of
 *  somebody else's typography.
 */

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { api } from '../lib/api'
import { useSettings } from '../lib/settings'
import type { NewsCalendar } from '../lib/types'
import { Card, CardHeader, EmptyState, ErrorState, Skeleton } from './ui'

/** ForexFactory's folder colours, which is how everyone refers to these. */
const IMPACT: Record<string, { color: string; label: string }> = {
  High: { color: 'var(--tz-loss)', label: 'Red folder' },
  Medium: { color: '#f59e0b', label: 'Orange folder' },
  Low: { color: '#eab308', label: 'Yellow folder' },
  Holiday: { color: 'var(--tz-text-faint)', label: 'Holiday' },
}

/** ForexFactory's own day page, e.g. .../calendar?day=aug4.2026.
 *
 *  The feed carries no id or link per release, so a row cannot point at
 *  itself. The day it falls on is as close as the data allows, and it lands
 *  you where the release is.
 */
function dayLink(iso: string): string {
  const when = new Date(iso)
  const month = when.toLocaleString('en-US', { month: 'short' }).toLowerCase()
  return `https://www.forexfactory.com/calendar?day=${month}${when.getDate()}.${when.getFullYear()}`
}

export function ForexFactoryCalendar({
  title = null,
  /** Hide what has already happened, which is most of what a Friday holds. */
  upcomingOnly = false,
}: {
  title?: string | null
  upcomingOnly?: boolean
}) {
  const { settings } = useSettings()
  const timezone = settings.general.timezone

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['news', 'forexfactory'],
    queryFn: () => api.get<NewsCalendar>('/news/calendar'),
    // The server holds the week for fifteen minutes; asking more often only
    // moves work around.
    staleTime: 10 * 60 * 1000,
  })

  if (isError) return <ErrorState error={error} retry={() => void refetch()} />

  const all = data?.events ?? []
  // A release that has been is history; nobody plans a session around it.
  // Given a few minutes' grace so the one that just landed does not vanish
  // while it is still the thing everyone is looking at.
  const since = Date.now() - 15 * 60 * 1000
  const events = upcomingOnly
    ? all.filter((event) => new Date(event.time).getTime() >= since)
    : all

  const byDay = new Map<string, typeof events>()
  for (const event of events) {
    const day = new Date(event.time).toLocaleDateString(undefined, {
      timeZone: timezone,
      weekday: 'long',
      day: 'numeric',
      month: 'long',
    })
    byDay.set(day, [...(byDay.get(day) ?? []), event])
  }

  const today = new Date().toLocaleDateString(undefined, {
    timeZone: timezone,
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })

  return (
    <Card padded={false}>
      {title && <div className="px-4 pt-4 sm:px-5"><CardHeader title={title} /></div>}

      {isLoading ? (
        <Skeleton className="m-4 h-64" />
      ) : events.length === 0 ? (
        <EmptyState
          title={
            data?.error
              ? 'The calendar could not be fetched'
              : upcomingOnly && all.length
                ? 'Nothing left this week'
                : 'Nothing scheduled'
          }
          description={
            data?.error
              ? `ForexFactory could not be reached: ${data.error}`
              : upcomingOnly && all.length
                ? // ForexFactory publishes one week at a time, Sunday to
                  // Saturday, and there is no next-week feed to read ahead
                  // from. Said plainly rather than leaving an empty panel.
                  'Every release you asked for has been and gone. ForexFactory publishes one week at a time — the week ahead appears on Sunday. Switch to “Whole week” to see what happened.'
                : 'No releases this week match the currencies and folders you picked. Widen them under Settings → General.'
          }
        />
      ) : (
        <div className="divide-y divide-[var(--tz-border)]">
          {[...byDay.entries()].map(([day, rows]) => (
            <div key={day}>
              <div
                className={
                  'sticky top-0 z-10 bg-[var(--tz-surface-2)] px-4 py-1.5 text-xs font-medium sm:px-5 ' +
                  (day === today ? 'text-[var(--tz-accent)]' : 'text-[var(--tz-text-muted)]')
                }
              >
                {day}
                {day === today && ' · today'}
              </div>
              {rows.map((event, index) => (
                <a
                  key={`${event.time}-${event.title}-${index}`}
                  href={dayLink(event.time)}
                  target="_blank"
                  rel="noreferrer noopener"
                  title="Open this day on ForexFactory"
                  className="flex items-baseline gap-3 px-4 py-2 text-sm transition-colors hover:bg-[var(--tz-surface-hover)] sm:px-5"
                >
                  <span className="tabular w-14 shrink-0 text-xs text-[var(--tz-text-muted)]">
                    {new Date(event.time).toLocaleTimeString(undefined, {
                      timeZone: timezone,
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </span>
                  <span
                    className="w-10 shrink-0 text-xs font-medium"
                    style={{ color: 'var(--tz-text)' }}
                  >
                    {event.currency}
                  </span>
                  <span
                    className="mt-1 size-2 shrink-0 rounded-[2px]"
                    style={{ backgroundColor: IMPACT[event.impact]?.color ?? 'var(--tz-flat)' }}
                    title={IMPACT[event.impact]?.label ?? event.impact}
                  />
                  <span className="min-w-0 flex-1">{event.title}</span>
                  {/* Forecast and previous only. The feed carries no actuals,
                      and a column that is always empty is worse than none. */}
                  {(event.forecast || event.previous) && (
                    <span className="tabular hidden shrink-0 text-xs text-[var(--tz-text-muted)] sm:block">
                      {event.forecast && <>forecast {event.forecast}</>}
                      {event.forecast && event.previous && ' · '}
                      {event.previous && <>prev {event.previous}</>}
                    </span>
                  )}
                </a>
              ))}
            </div>
          ))}
        </div>
      )}

      {data?.stale && (
        <p className="flex items-center gap-1.5 border-t border-[var(--tz-border)] px-4 py-2 text-xs text-[var(--tz-text-muted)] sm:px-5">
          <AlertTriangle size={12} />
          ForexFactory is rate-limiting us, so this is the last copy that came through
          {data.updated_at
            ? ` (${new Date(data.updated_at).toLocaleString(undefined, { timeZone: timezone })}).`
            : '.'}
        </p>
      )}
    </Card>
  )
}
