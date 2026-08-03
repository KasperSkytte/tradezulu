/** The economic calendar, on a page of its own.
 *
 *  It began on the dashboard, which was the wrong place for it: the dashboard
 *  answers "how am I doing", entirely from your own trades, and a panel of
 *  other people's announcements in the middle of that answers nothing. It is
 *  also the thing you want *before* the session rather than after it, which is
 *  a different visit to the site.
 */

import { NewsCalendar } from '../components/NewsCalendar'
import { useSettings } from '../lib/settings'

export function NewsPage() {
  const { settings } = useSettings()
  const countries = settings.news?.countries ?? ['us']
  const importance = settings.news?.importance ?? 1

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">News</h1>
        <p className="mt-1 text-sm text-[var(--tz-text-muted)]">
          {importance === 1 ? 'High-impact releases' : 'Scheduled releases'} for{' '}
          {countries.map((code) => code.toUpperCase()).join(', ')} — when spreads widen and stops
          get run. Change which countries and what impact level under Settings → General.
        </p>
      </div>

      {/* Tall here, where it is the whole page, rather than the panel-sized
          box it was on the dashboard: the point of a calendar is seeing the
          week without scrolling a frame inside a page. */}
      <NewsCalendar height={720} title={null} />
    </div>
  )
}
