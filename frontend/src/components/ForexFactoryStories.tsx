/** The headlines, beside the calendar.
 *
 *  The calendar says what is scheduled; this says what has happened. Both come
 *  from ForexFactory and carry the same folder ratings, so a red-folder story
 *  and a red-folder release read alike — which is the reason for showing their
 *  news rather than a general wire: somebody has already decided which of a
 *  hundred sources' headlines move a market.
 */

import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ExternalLink, MessageSquare } from 'lucide-react'
import { api } from '../lib/api'
import { useNow } from '../lib/clock'
import { useSettings } from '../lib/settings'
import type { NewsStories } from '../lib/types'
import { Card, CardHeader, EmptyState, ErrorState, Skeleton } from './ui'

/** The same folder colours the calendar uses. */
const IMPACT: Record<string, { color: string; label: string }> = {
  High: { color: 'var(--tz-impact-high)', label: 'Red folder' },
  Medium: { color: 'var(--tz-impact-medium)', label: 'Orange folder' },
  Low: { color: 'var(--tz-impact-low)', label: 'Yellow folder' },
}

/** How long ago, in the words the source page uses. */
function ago(iso: string, now: number): string {
  const seconds = Math.max(0, (now - new Date(iso).getTime()) / 1000)
  if (seconds < 90) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} hr ${minutes % 60} min ago`
  const days = Math.round(hours / 24)
  return days === 1 ? 'yesterday' : `${days} days ago`
}

/** When it came out, on the journal's clock -- and only then how long ago.
 *
 *  An age on its own cannot be checked against anything. "2 hr 12 min ago" is
 *  either right or wrong and there is no way to tell which, so a page that has
 *  been open a while, or a story the source filed late, both read as a bug.
 *  The time it came out is a fact that survives being looked at twice; the age
 *  beside it is the part that answers "is this still news".
 */
function when(iso: string, now: number, timezone: string, hour12: boolean): string {
  const at = new Date(iso)
  const clock = at.toLocaleTimeString(hour12 ? 'en-US' : 'en-GB', {
    timeZone: timezone,
    hour: hour12 ? 'numeric' : '2-digit',
    minute: '2-digit',
    hour12,
  })
  const sameDay =
    at.toLocaleDateString('en-CA', { timeZone: timezone }) ===
    new Date(now).toLocaleDateString('en-CA', { timeZone: timezone })
  // A story from yesterday needs the day as well, or 23:40 reads as tonight.
  const day = sameDay
    ? ''
    : `${at.toLocaleDateString(undefined, { timeZone: timezone, weekday: 'short' })} `
  return `${day}${clock}`
}

export function ForexFactoryStories({ title = 'News' }: { title?: string | null }) {
  const { settings, hour12 } = useSettings()
  const impacts = settings.news?.story_impacts ?? []
  // Ages are only true at the moment they are drawn, so this redraws them.
  const now = useNow()
  const timezone = settings.general.timezone

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['news', 'stories', impacts.join(',')],
    queryFn: () => api.get<NewsStories>('/news/stories', { impacts: impacts.join(',') }),
    // The server holds them for five minutes; asking more often only moves
    // work around.
    staleTime: 4 * 60 * 1000,
  })

  if (isError) return <ErrorState error={error} retry={() => void refetch()} />

  return (
    <Card padded={false}>
      {title && (
        <div className="px-4 pt-4 sm:px-5">
          <CardHeader
            title={title}
            hint="Stories ForexFactory carries from other sources, rated the way its calendar rates releases. Which ratings appear is under Settings → General."
            action={
              data?.updated_at ? (
                <span className="text-xs text-[var(--tz-text-faint)]">
                  {data.stale ? 'last held copy' : `updated ${ago(data.updated_at, now)}`}
                </span>
              ) : null
            }
          />
        </div>
      )}

      {data?.stale && (
        <p className="mx-4 mb-2 flex items-start gap-2 rounded-lg border border-[var(--tz-border)] bg-[var(--tz-surface-2)] px-3 py-2 text-xs text-[var(--tz-text-muted)] sm:mx-5">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          ForexFactory did not answer the last refresh, so these are the stories held from
          before.
        </p>
      )}

      {isLoading ? (
        <Skeleton className="m-4 h-[420px] sm:m-5" />
      ) : !data?.stories.length ? (
        <div className="p-4 sm:p-5">
          <EmptyState
            title="Nothing at this rating"
            description={
              data?.error
                ? 'ForexFactory did not answer. It will be tried again shortly.'
                : 'Widen the ratings under Settings → General to see more.'
            }
          />
        </div>
      ) : (
        <ul className="divide-y divide-[var(--tz-border)] border-t border-[var(--tz-border)]">
          {data.stories.map((story, index) => {
            const folder = IMPACT[story.impact]
            // The hover background on the last row would square off the
            // card's bottom corners, the same way the calendar's did.
            const last = index === data.stories.length - 1
            return (
              <li key={story.id}>
                <a
                  href={story.url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className={
                    'group flex gap-3 px-4 py-3 transition-colors ' +
                    'hover:bg-[var(--tz-surface-hover)] sm:px-5 ' +
                    (last ? 'rounded-b-[var(--radius-card)]' : '')
                  }
                >
                  {/* The folder colour, in the same place the calendar puts
                      it, so the two panels scan as one thing. */}
                  <span
                    className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full"
                    style={{
                      background: folder?.color ?? 'var(--tz-border-strong)',
                      boxShadow: 'inset 0 0 0 1px var(--tz-impact-ring)',
                    }}
                    title={folder?.label ?? 'Unrated'}
                  />
                  <span className="min-w-0">
                    <span className="block text-sm font-medium leading-snug group-hover:text-zulu-400">
                      {story.title}
                      <ExternalLink
                        size={11}
                        className="ml-1 inline shrink-0 text-[var(--tz-text-faint)]"
                      />
                    </span>
                    <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--tz-text-faint)]">
                      <span>{story.source}</span>
                      <span>·</span>
                      <span title={ago(story.time, now)}>
                        {when(story.time, now, timezone, hour12)}
                      </span>
                      <span>·</span>
                      <span>{ago(story.time, now)}</span>
                      {/* A story tied to a calendar release is one of *the*
                          numbers rather than commentary about them. */}
                      {story.scheduled && (
                        <>
                          <span>·</span>
                          <span className="text-[var(--tz-text-muted)]">scheduled release</span>
                        </>
                      )}
                      {story.comments > 0 && (
                        <>
                          <span>·</span>
                          <span className="inline-flex items-center gap-1">
                            <MessageSquare size={11} />
                            {story.comments}
                          </span>
                        </>
                      )}
                    </span>
                  </span>
                </a>
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}
