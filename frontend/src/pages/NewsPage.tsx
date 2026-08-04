/** The economic calendar, on a page of its own.
 *
 *  It began on the dashboard, which was the wrong place for it: the dashboard
 *  answers "how am I doing", entirely from your own trades, and a panel of
 *  other people's announcements in the middle of that answers nothing. It is
 *  also the thing you want *before* the session rather than after it, which is
 *  a different visit to the site.
 *
 *  Two sources, because they disagree about what matters and people have a
 *  side: TradingView's widget brings its own data and its own look;
 *  ForexFactory is the one traders quote folder colours from. The choice is
 *  saved with the settings rather than in this browser, so it survives logging
 *  in from the phone.
 */

import { ForexFactoryCalendar } from '../components/ForexFactoryCalendar'
import { NewsCalendar } from '../components/NewsCalendar'
import { useSettings } from '../lib/settings'
import { SegmentedControl } from '../components/ui'

export function NewsPage() {
  const { settings, save } = useSettings()
  const news = settings.news
  const provider = news?.provider ?? 'tradingview'

  const countries = news?.countries ?? ['us']
  const importance = news?.importance ?? 1
  const currencies = news?.currencies ?? ['USD']
  const impacts = news?.impacts ?? ['High']

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">News</h1>
          <p className="mt-1 max-w-2xl text-sm text-[var(--tz-text-muted)]">
            {provider === 'forexfactory' ? (
              <>
                {impacts.includes('High') && impacts.length === 1
                  ? 'Red-folder releases'
                  : 'Scheduled releases'}{' '}
                for {currencies.join(', ')} — when spreads widen and stops get run.
              </>
            ) : (
              <>
                {importance === 1 ? 'High-impact releases' : 'Scheduled releases'} for{' '}
                {countries.map((code) => code.toUpperCase()).join(', ')} — when spreads widen
                and stops get run.
              </>
            )}{' '}
            Which currencies and what impact level to show are under Settings → General.
          </p>
        </div>

        <SegmentedControl
          size="sm"
          value={provider}
          onChange={(value) => void save({ news: { provider: value } })}
          options={[
            { value: 'tradingview', label: 'TradingView', title: "TradingView's own widget" },
            {
              value: 'forexfactory',
              label: 'ForexFactory',
              title: 'ForexFactory’s published calendar, drawn here',
            },
          ]}
        />
      </div>

      {provider === 'forexfactory' ? (
        <ForexFactoryCalendar />
      ) : (
        /* Tall here, where it is the whole page, rather than the panel-sized
           box it was on the dashboard: the point of a calendar is seeing the
           week without scrolling a frame inside a page. */
        <NewsCalendar height={720} title={null} />
      )}
    </div>
  )
}
