/** The economic calendar, on a page of its own.
 *
 *  It began on the dashboard, which was the wrong place for it: the dashboard
 *  answers "how am I doing", entirely from your own trades, and a panel of
 *  other people's announcements in the middle of that answers nothing. It is
 *  also the thing you want *before* the session rather than after it, which is
 *  a different visit to the site.
 *
 *  Two sources, because they disagree about what matters and people have a
 *  side: ForexFactory is the one traders quote folder colours from, and is
 *  drawn here from its published feed; TradingView's widget brings its own
 *  data and its own look. The choice is saved with the settings rather than in
 *  this browser, so it survives logging in from the phone.
 */

import { ForexFactoryCalendar } from '../components/ForexFactoryCalendar'
import { NewsCalendar } from '../components/NewsCalendar'
import { useSettings } from '../lib/settings'
import { SegmentedControl } from '../components/ui'

export function NewsPage() {
  const { settings, save } = useSettings()
  const news = settings.news
  const provider = news?.provider ?? 'forexfactory'
  const range = news?.range ?? 'upcoming'

  return (
    <div className="space-y-4">
      {/* Controls first and on the left, where the eye starts: which calendar
          and how much of it are the two questions asked on arrival. */}
      <div className="flex flex-wrap items-center gap-2">
        <SegmentedControl
          size="sm"
          value={provider}
          onChange={(value) => void save({ news: { provider: value } })}
          options={[
            {
              value: 'forexfactory',
              label: 'ForexFactory',
              title: 'ForexFactory’s published calendar, drawn here',
            },
            { value: 'tradingview', label: 'TradingView', title: "TradingView's own widget" },
          ]}
        />
        {provider === 'forexfactory' && (
          <SegmentedControl
            size="sm"
            value={range}
            onChange={(value) => void save({ news: { range: value } })}
            options={[
              { value: 'upcoming', label: 'Upcoming', title: 'From now to the end of the week' },
              { value: 'week', label: 'Whole week', title: 'Including what has already been' },
            ]}
          />
        )}
      </div>

      {provider === 'forexfactory' ? (
        <ForexFactoryCalendar upcomingOnly={range === 'upcoming'} />
      ) : (
        /* Tall here, where it is the whole page, rather than the panel-sized
           box it was on the dashboard: the point of a calendar is seeing the
           week without scrolling a frame inside a page. */
        <NewsCalendar height={720} title={null} />
      )}

      {/* Below the calendar: it is the reason the page exists, but it is the
          same paragraph every visit, and nobody should scroll past what they
          came to read to get to it. */}
      <div className="max-w-3xl space-y-2 border-t border-[var(--tz-border)] pt-4 text-sm text-[var(--tz-text-muted)]">
        <p>
          Price tends to move sharply around scheduled releases — inflation and unemployment
          figures, and central bank decisions on rates above all. When it moves quickly enough,
          your stop does <strong>not</strong> trigger where you placed it: slippage turns a
          measured loss into a much larger one. So be careful around these.
        </p>
        <p>
          Bank holidays cut the other way. A day with nothing on it tends to range, produces no
          setup worth taking, and is better spent doing something meaningful with your life.
        </p>
        <p>
          Which currencies and which folders to show are under{' '}
          <span className="text-[var(--tz-text)]">Settings → General</span>.
        </p>
      </div>
    </div>
  )
}
