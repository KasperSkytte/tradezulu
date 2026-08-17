/** The week's releases, from ForexFactory's own feed.
 *
 *  Not an embed: ForexFactory sits behind a Cloudflare challenge and sends
 *  X-Frame-Options: SAMEORIGIN, so an iframe of it shows a 403 page. The
 *  server reads their published JSON instead and this draws it, which also
 *  means it matches the rest of the journal rather than being a rectangle of
 *  somebody else's typography.
 */

import { Fragment } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { api } from '../lib/api'
import { useNow } from '../lib/clock'
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

/** The calendar date a moment falls on, in the zone the journal is written in.
 *
 *  ISO order rather than a heading, because these are sorted and walked. The
 *  heading is made from the key when the day is drawn.
 */
function dayKey(iso: string, timezone: string): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: timezone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(iso))
}

/** Midday rather than midnight: a date read back in another zone keeps its
 *  own day either way, which midnight does not. */
function dayLabel(key: string, timezone: string): string {
  return new Date(`${key}T12:00:00Z`).toLocaleDateString(undefined, {
    timeZone: timezone,
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })
}

const minKey = (a: string, b: string) => (a < b ? a : b)
const maxKey = (a: string, b: string) => (a > b ? a : b)

/** Every date from one key to the other, inclusive. Capped: the feed carries
 *  one week, and a stale or malformed one must not draw a year of headings. */
function fillDays(from: string, to: string): string[] {
  const out: string[] = []
  const cursor = new Date(`${from}T12:00:00Z`)
  const end = new Date(`${to}T12:00:00Z`)
  while (cursor <= end && out.length < 14) {
    out.push(cursor.toISOString().slice(0, 10))
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  return out
}

/** Where the week is up to: everything above has happened, nothing below has.
 *
 *  Drawn as a line rather than a highlighted row because it falls *between*
 *  two releases -- often between two days -- and belongs to neither.
 */
function NowLine({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-1 sm:px-5" aria-label={`Now, ${label}`}>
      <span className="tabular w-16 shrink-0 text-right text-[11px] font-medium text-[var(--tz-accent)]">
        {label}
      </span>
      <span className="h-px flex-1 bg-[var(--tz-accent)] opacity-70" />
      <span className="text-[10px] font-medium uppercase tracking-wide text-[var(--tz-accent)]">
        now
      </span>
    </div>
  )
}

export function ForexFactoryCalendar({
  title = null,
  /** Hide what has already happened, which is most of what a Friday holds. */
  upcomingOnly = false,
}: {
  title?: string | null
  upcomingOnly?: boolean
}) {
  const { settings, hour12 } = useSettings()
  const now = useNow(!upcomingOnly)
  const timezone = settings.general.timezone
  // These rows need the configured timezone, which the date-fns helpers do not
  // take, so they format their own times -- and then have to match the rest of
  // the journal by hand. The browser's own locale does not: en-GB writes
  // "04:00 pm" where everything else here writes "4:00 PM".
  const clock = hour12 ? 'en-US' : 'en-GB'

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

  // Keyed by the calendar date in the configured zone, so the days can be
  // walked in order and the gaps found. The heading is formatted from the key
  // rather than from an event, because a day may now have no events at all.
  const byDay = new Map<string, typeof events>()
  for (const event of events) {
    const day = dayKey(event.time, timezone)
    byDay.set(day, [...(byDay.get(day) ?? []), event])
  }

  const todayKey = dayKey(new Date(now).toISOString(), timezone)

  // Whole week means the whole week, empty days included. Leaving them out
  // moved "now" under the next day that happened to have a release -- so on a
  // quiet Tuesday the line sat below Wednesday's heading, reading as though
  // the day had already turned.
  const dayList = [...byDay.keys()].sort()
  const days = upcomingOnly
    ? dayList
    : fillDays(
        dayList.length ? minKey(dayList[0], todayKey) : todayKey,
        dayList.length ? maxKey(dayList[dayList.length - 1], todayKey) : todayKey,
      )

  // The line belongs to today, wherever today's releases have got to -- above
  // the first one still to come, or after the last one when they have all
  // been. Anchoring it to "the next release anywhere in the week" put it under
  // tomorrow's heading whenever today had nothing on, which read as though the
  // day had already turned.
  //
  // Only in whole-week mode: with the past hidden every row is upcoming, and a
  // line above all of them says nothing.
  const marksToday = !upcomingOnly && days.includes(todayKey)
  const clockTime = new Date(now).toLocaleTimeString(clock, {
    timeZone: timezone,
    hour: hour12 ? 'numeric' : '2-digit',
    minute: '2-digit',
    hour12,
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
          {days.map((day, group) => {
            const rows = byDay.get(day) ?? []
            const isToday = day === todayKey
            // Today's first release still to come. The line goes above it, or
            // after everything when the day is done -- including a day with
            // nothing on it at all, where the group is the line by itself.
            const upcoming = isToday
              ? rows.find((event) => new Date(event.time).getTime() > now)
              : undefined
            return (
            <div key={day}>
              <div
                className={
                  'sticky top-0 z-10 bg-[var(--tz-surface-2)] px-4 py-1.5 text-xs font-medium sm:px-5 ' +
                  // The first bar sits in the card's own top corners when
                  // nothing is above it, and a square background over a
                  // rounded corner squares the corner off.
                  (group === 0 && !title ? 'rounded-t-[var(--radius-card)] ' : '') +
                  (isToday ? 'text-[var(--tz-accent)]' : 'text-[var(--tz-text-muted)]')
                }
              >
                {dayLabel(day, timezone)}
                {isToday && ' · today'}
              </div>
              {rows.map((event, index) => (
                <Fragment key={`${event.time}-${event.title}-${index}`}>
                {marksToday && event === upcoming && <NowLine label={clockTime} />}
                <a
                  href={dayLink(event.time)}
                  target="_blank"
                  rel="noreferrer noopener"
                  title="Open this day on ForexFactory"
                  className={
                    'flex items-baseline gap-3 px-4 py-2 text-sm transition-colors ' +
                    'hover:bg-[var(--tz-surface-hover)] sm:px-5 ' +
                    // Same at the bottom, where the hover background would
                    // otherwise square the last two corners.
                    (group === days.length - 1 &&
                    index === rows.length - 1 &&
                    !(marksToday && isToday && !upcoming) &&
                    !data?.stale
                      ? 'rounded-b-[var(--radius-card)]'
                      : '')
                  }
                >
                  <span className="tabular w-16 shrink-0 text-xs text-[var(--tz-text-muted)]">
                    {new Date(event.time).toLocaleTimeString(clock, {
                      timeZone: timezone,
                      hour: hour12 ? 'numeric' : '2-digit',
                      minute: '2-digit',
                      hour12,
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
                </Fragment>
              ))}
              {/* A day nobody scheduled anything on. Said rather than left
                  out, so the week reads as a week -- and so today saying
                  nothing is a day off rather than a day missing. */}
              {rows.length === 0 && (
                <p className="px-4 py-2 text-xs text-[var(--tz-text-faint)] sm:px-5">
                  Nothing scheduled
                </p>
              )}
              {/* Today is over, or had nothing on it: the line closes the day
                  rather than opening tomorrow. */}
              {marksToday && isToday && !upcoming && <NowLine label={clockTime} />}
            </div>
            )
          })}
        </div>
      )}

      {data?.stale && (
        <p className="flex items-center gap-1.5 border-t border-[var(--tz-border)] px-4 py-2 text-xs text-[var(--tz-text-muted)] sm:px-5">
          <AlertTriangle size={12} />
          ForexFactory is rate-limiting us, so this is the last copy that came through
          {data.updated_at
            ? ` (${new Date(data.updated_at).toLocaleString(clock, { timeZone: timezone, hour12 })}).`
            : '.'}
        </p>
      )}
    </Card>
  )
}
