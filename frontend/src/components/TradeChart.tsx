/**
 * Trade replay.
 *
 * Two providers, both free:
 *  - "klinecharts" draws the candles TradeZulu already holds -- pushed by the
 *    Expert Advisor -- with the position itself on them: a line from entry to
 *    exit, the risk shaded below and the target above, every fill on the
 *    minute it filled, and drawing tools on top. See KLineReplay.
 *  - "tradingview" embeds the free Advanced Chart widget, which has every
 *    drawing tool and no knowledge of your trade.
 *
 * There was a third, drawing the same stored candles with lightweight-charts.
 * It did strictly less than the first -- price lines running the width of the
 * chart instead of the position, fills snapped to the nearest bar, no drawing
 * tools -- so it was two charts to maintain for one job.
 */

import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { ExternalLink } from 'lucide-react'
import { api } from '../lib/api'
import { KLineReplay } from './KLineReplay'
import { useIsDark, useSettings } from '../lib/settings'
import { dateTime } from '../lib/format'
import type { Account, BrokerList, CandleResponse, TradeDetail } from '../lib/types'
import { SegmentedControl } from './ui'

const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1']

/** The widest window the free embed can be asked for, in days.
 *
 *  TradingView's embed takes a *relative* range and nothing else -- its whole
 *  parameter list is symbol, interval, theme, studies and this. There is no
 *  from/to and no way to scroll it to a date from outside the iframe, so a
 *  chart of a trade from March cannot be centred on March. What it can do is
 *  reach back far enough that March is still on screen, which is the
 *  difference between "my trade is in here somewhere" and a chart of today.
 */
const TV_RANGES: [days: number, range: string][] = [
  [1, '1D'],
  [5, '5D'],
  [30, '1M'],
  [90, '3M'],
  [180, '6M'],
  [365, '12M'],
]

function rangeCovering(when: string | null): string {
  if (!when) return '5D'
  const days = (Date.now() - new Date(when).getTime()) / 86_400_000
  // A little margin, so a trade from four days ago does not sit on the very
  // left edge of a five-day chart.
  const found = TV_RANGES.find(([limit]) => days * 1.25 + 1 < limit)
  return found ? found[1] : 'ALL'
}

const TV_INTERVAL: Record<string, string> = {
  M1: '1',
  M5: '5',
  M15: '15',
  M30: '30',
  H1: '60',
  H4: '240',
  D1: 'D',
}

type Provider = 'klinecharts' | 'tradingview'

export function TradeChart({ trade }: { trade: TradeDetail }) {
  const { settings } = useSettings()
  const [provider, setProvider] = useState<Provider>(settings.charts.provider)
  const [timeframe, setTimeframe] = useState(settings.charts.default_timeframe || 'M15')

  // Which timeframes the replay can actually draw. The terminal collects one
  // and the server folds the longer ones out of it, so the answer depends on
  // the symbol -- and a button that can only ever be empty is worse than no
  // button. TradingView brings its own data, so it keeps the full list.
  //
  // Same query key as the chart below, so this shares its request rather than
  // making a second one.
  const { data } = useQuery({
    queryKey: ['candles', trade.id, timeframe],
    queryFn: () =>
      api.get<CandleResponse>('/mt5/candles', { trade_id: trade.id, timeframe }),
    enabled: provider !== 'tradingview',
  })
  const offered =
    provider === 'tradingview' || !data?.available?.length ? TIMEFRAMES : data.available

  // Landing on a timeframe this symbol has no bars for shows an empty chart
  // that looks broken. Move to the closest one that works instead.
  useEffect(() => {
    if (offered.length && !offered.includes(timeframe)) setTimeframe(offered[0])
  }, [offered, timeframe])

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <SegmentedControl
          size="sm"
          value={provider}
          onChange={setProvider}
          options={[
            {
              value: 'klinecharts',
              label: 'KLineCharts',
              title: 'Candles TradeZulu stored, with the position drawn on them',
            },
            { value: 'tradingview', label: 'TradingView', title: 'Free TradingView widget' },
          ]}
        />
        <SegmentedControl
          size="sm"
          value={timeframe}
          onChange={setTimeframe}
          options={offered.map((value) => ({ value, label: value }))}
        />
      </div>

      {provider === 'klinecharts' ? (
        <KLineReplay trade={trade} timeframe={timeframe} />
      ) : (
        <TradingViewChart trade={trade} timeframe={timeframe} />
      )}
    </div>
  )
}

/* --------------------------------------------------------------------- */

function TradingViewChart({ trade, timeframe }: { trade: TradeDetail; timeframe: string }) {
  const container = useRef<HTMLDivElement>(null)
  const { settings } = useSettings()
  const dark = useIsDark()

  // Which exchange TradingView should look the symbol up on. Nobody should
  // have to know that a Vantage feed is "VANTAGE:", so it is worked out from
  // the broker the account is with -- and a prefix set by hand still wins,
  // because a broker can be on a feed the list has not heard of.
  const { data: brokerList } = useQuery({
    queryKey: ['mt5-brokers'],
    queryFn: () => api.get<BrokerList>('/mt5/brokers'),
    staleTime: 60 * 60 * 1000,
  })
  const { data: accounts = [] } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => api.get<Account[]>('/accounts'),
    staleTime: 300_000,
  })
  const detected = (() => {
    const account = accounts.find((a) => a.id === trade.account_id)
    const haystack = `${account?.broker ?? ''} ${account?.server ?? ''}`.toLowerCase()
    const broker = (brokerList?.brokers ?? []).find((b) =>
      (b.matches ?? []).some((m) => m && haystack.includes(m.toLowerCase())),
    )
    return broker?.tradingview_prefix ?? ''
  })()

  // Brokers decorate their symbols -- XAUUSD+, EURUSD.r, US30cash -- and
  // TradingView knows none of those, so the widget silently shows nothing.
  // An explicit mapping still wins; this is only for the common case of a
  // suffix bolted onto an otherwise ordinary ticker.
  const bare = trade.symbol.replace(/[^A-Z0-9]+$/, '') || trade.symbol
  const mapped = settings.charts.symbol_map[trade.symbol] ?? settings.charts.symbol_map[bare]
  const prefix = settings.charts.tradingview_prefix || detected
  const symbol = mapped || `${prefix}${bare}`

  useEffect(() => {
    const element = container.current
    if (!element) return
    element.innerHTML = ''

    const widget = document.createElement('div')
    widget.className = 'tradingview-widget-container__widget'
    widget.style.height = '100%'
    widget.style.width = '100%'
    element.appendChild(widget)

    const script = document.createElement('script')
    script.src =
      'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js'
    script.async = true
    script.type = 'text/javascript'
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol,
      interval: TV_INTERVAL[timeframe] ?? '15',
      // Wide enough to still contain the trade. It cannot be centred on it --
      // see TV_RANGES.
      range: rangeCovering(trade.closed_at ?? trade.opened_at),
      timezone: settings.general.timezone,
      theme: dark ? 'dark' : 'light',
      style: '1',
      locale: 'en',
      hide_side_toolbar: false,
      allow_symbol_change: true,
      save_image: false,
      details: false,
      withdateranges: true,
      support_host: 'https://www.tradingview.com',
    })
    element.appendChild(script)

    return () => {
      element.innerHTML = ''
    }
  }, [symbol, timeframe, settings.general.timezone, dark, trade.closed_at, trade.opened_at])

  return (
    <div>
      {/* The embed takes the container over and forces height:100% on it, so
          the concrete height has to live on a parent for that to resolve —
          without this wrapper it collapses to a 150px strip. */}
      <div style={{ height: 460 }} className="w-full">
        <div
          className="tradingview-widget-container w-full"
          style={{ height: '100%' }}
          ref={container}
        />
      </div>
      <p className="mt-2 text-xs text-[var(--tz-text-faint)]">
        TradingView's embed always ends at the current price and cannot be moved to a date from
        outside it, so the window is widened until your trade falls inside it:{' '}
        <strong>{dateTime(trade.closed_at ?? trade.opened_at, undefined, trade.account_id)}</strong>.
        KLineCharts opens on the trade itself, with your fills marked.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--tz-text-muted)]">
        <a
          className="ml-auto flex items-center gap-1 hover:text-[var(--tz-text)]"
          href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(symbol)}`}
          target="_blank"
          rel="noreferrer noopener"
        >
          Open on TradingView <ExternalLink size={12} />
        </a>
      </div>
      {!mapped && (
        <p className="mt-2 text-xs text-[var(--tz-text-faint)]">
          Showing <code>{symbol}</code>. If that is not the right ticker, map it in Settings →
          Charts.
        </p>
      )}
    </div>
  )
}
