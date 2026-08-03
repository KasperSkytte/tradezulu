/** The economic calendar, from TradingView's free widget.
 *
 *  High-impact US releases only by default. Everything else is noise for most
 *  people most of the time, and a calendar showing forty entries a day is one
 *  nobody reads — which is worse than not having it, because it looks like
 *  cover.
 */

import { useEffect, useRef } from 'react'
import { useIsDark, useSettings } from '../lib/settings'
import { Card, CardHeader } from './ui'

export function NewsCalendar({
  height = 420,
  /** Null on a page that already says what this is, so it is not titled twice. */
  title = 'Economic calendar',
}: {
  height?: number
  title?: string | null
}) {
  const container = useRef<HTMLDivElement>(null)
  const { settings } = useSettings()
  const dark = useIsDark()
  const news = settings.news ?? { countries: ['us'], importance: 1 }

  const countries = (news.countries ?? ['us']).join(',')
  const importance = news.importance ?? 1
  const timezone = settings.general.timezone

  useEffect(() => {
    const element = container.current
    if (!element) return
    element.innerHTML = ''

    const widget = document.createElement('div')
    widget.className = 'tradingview-widget-container__widget'
    element.appendChild(widget)

    const script = document.createElement('script')
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-events.js'
    script.async = true
    script.type = 'text/javascript'
    script.innerHTML = JSON.stringify({
      colorTheme: dark ? 'dark' : 'light',
      // Not transparent: the widget then paints nothing and the iframe's own
      // white shows through, which on a dark page is a white slab.
      isTransparent: false,
      width: '100%',
      height,
      locale: 'en',
      // 1 is TradingView's "high impact". -1 would include everything.
      importanceFilter: String(importance),
      countryFilter: countries,
      timezone,
    })
    element.appendChild(script)

    return () => {
      element.innerHTML = ''
    }
  }, [countries, importance, timezone, height, dark])

  return (
    <Card>
      {title && (
        <CardHeader
          title={title}
          hint="High-impact releases, which is when spreads widen and stops get run. Which countries and what impact level to show are under Settings → General."
        />
      )}
      <div
        className="tradingview-widget-container"
        ref={container}
        style={{ height, width: '100%' }}
      />
    </Card>
  )
}
