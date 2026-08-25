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

import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { RefreshCw } from 'lucide-react'
import { ForexFactoryCalendar } from '../components/ForexFactoryCalendar'
import { ForexFactoryStories } from '../components/ForexFactoryStories'
import { NewsCalendar } from '../components/NewsCalendar'
import { api } from '../lib/api'
import { useSettings } from '../lib/settings'
import { Button, SegmentedControl } from '../components/ui'

export function NewsPage() {
  const { settings, save } = useSettings()
  const queryClient = useQueryClient()
  const news = settings.news
  const provider = news?.provider ?? 'forexfactory'
  const range = news?.range ?? 'upcoming'
  const stories = news?.stories ?? true

  // TradingView's widget holds its own data and offers no way in, so the only
  // refresh available for it is building the thing again -- which is what
  // changing this key does.
  const [widget, setWidget] = useState(0)

  // Not the header's refresh, which re-reads what the browser already has:
  // both of these are held on the server for minutes at a time, so a refresh
  // that means anything has to ask the server to go back to ForexFactory. It
  // is throttled at that end -- the feed rate-limits hard, and a button is an
  // easy way to get blocked.
  const refresh = useMutation({
    mutationFn: async () => {
      if (provider === 'tradingview') {
        setWidget((n) => n + 1)
        return
      }
      await Promise.all([
        api.get('/news/calendar', { force: true }),
        stories ? api.get('/news/stories', { force: true }) : Promise.resolve(null),
      ])
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['news'] }),
  })

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
        <Button
          className="ml-auto"
          onClick={() => refresh.mutate()}
          loading={refresh.isPending}
          icon={<RefreshCw size={15} />}
          title={
            provider === 'tradingview'
              ? "Build TradingView's widget again"
              : 'Read the calendar and the headlines from ForexFactory again, rather than from the copy held here'
          }
        >
          Refresh news
        </Button>
      </div>

      {provider === 'forexfactory' ? (
        /* Calendar and stories side by side on a desktop, and the calendar
           first on a phone: two columns of a week's releases and a wire feed
           in a 375px window leaves neither readable, and the calendar is what
           the page is for. ForexFactory only -- TradingView's provider is one
           embedded widget with nothing to put beside it. */
        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <ForexFactoryCalendar upcomingOnly={range === 'upcoming'} />
          {stories && <ForexFactoryStories />}
        </div>
      ) : (
        /* Tall here, where it is the whole page, rather than the panel-sized
           box it was on the dashboard: the point of a calendar is seeing the
           week without scrolling a frame inside a page. */
        <NewsCalendar key={widget} height={720} title={null} />
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
