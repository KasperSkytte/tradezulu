/**
 * Trade replay.
 *
 * Three providers, all free:
 *  - "local" draws candles TradeZulu already holds (pushed by the Expert
 *    Advisor) with the real entry, exit, stop and target marked on the price
 *    scale. This is the one that can show *your* fills, so it is the default.
 *  - "studio" draws the same candles with the position itself on them -- a box
 *    from entry to exit, the risk shaded below and the target above -- plus
 *    drawing tools. See KLineReplay.
 *  - "tradingview" embeds the free Advanced Chart widget, which has every
 *    drawing tool but no knowledge of your trade; entry and exit are listed
 *    beside it so you can find them on the chart.
 */

import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  LineStyle,
  TickMarkType,
  createChart,
  createSeriesMarkers,
} from 'lightweight-charts'
import type {
  IChartApi,
  IPriceLine,
  ISeriesApi,
  ISeriesMarkersPluginApi,
  Time,
} from 'lightweight-charts'
import { CandlestickChart, ExternalLink } from 'lucide-react'
import { api } from '../lib/api'
import { KLineReplay } from './KLineReplay'
import { useIsDark, useSettings } from '../lib/settings'
import { dateTime, price } from '../lib/format'
import type { Account, BrokerList, CandleResponse, TradeDetail } from '../lib/types'
import { EmptyState, SegmentedControl, Skeleton } from './ui'

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

/**
 * Seconds since the epoch for a timestamp the API returned.
 *
 * Every time in the journal is the broker's server clock -- MetaTrader has no
 * other -- but they do not all come back written the same way: candles are
 * marked UTC, executions are not. `Date.parse` reads an unmarked timestamp as
 * the *viewer's* local time, so the entry arrow was placed an hour or two from
 * the candle it belongs to, in whichever direction the reader happened to be
 * sitting, and by a different amount in summer than in winter.
 *
 * Both are put on one clock here instead. The chart is then internally
 * consistent wherever it is read from, and the axis reads the same as the
 * terminal the trade was taken in.
 */
function brokerTime(value: string): Time {
  const marked = /Z$|[+-]\d\d:?\d\d$/.test(value)
  return (Date.parse(marked ? value : `${value}Z`) / 1000) as Time
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

type Provider = 'local' | 'studio' | 'tradingview'

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
            { value: 'local', label: 'Replay', title: 'Candles stored by TradeZulu' },
            {
              value: 'studio',
              label: 'Studio',
              title: 'The same candles, with the position drawn on them and drawing tools',
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

      {provider === 'local' && <LocalReplay trade={trade} timeframe={timeframe} />}
      {provider === 'studio' && <KLineReplay trade={trade} timeframe={timeframe} />}
      {provider === 'tradingview' && <TradingViewChart trade={trade} timeframe={timeframe} />}
    </div>
  )
}

/* --------------------------------------------------------------------- */

/**
 * Which clock the axis is labelled with.
 *
 * The candles are never moved. A bar belongs to the minute the broker matched
 * it in, and rewriting that to suit the reader would mean the chart no longer
 * agreed with the terminal, the trade ticket, or the next person's screenshot.
 * Only the labels change -- the same instants, read off a different clock.
 *
 * ``offsetMinutes`` is how far the broker's clock runs from UTC, so subtracting
 * it turns a broker wall-clock stamp back into the real moment; ``timeZone``
 * then says how to write that moment down. Staying on the broker's clock is
 * the pair (0, UTC), because that is exactly what the stored timestamps
 * already are.
 */
type Clock = { hour12: boolean; offsetMinutes: number; timeZone: string }

function axisLabels({ hour12, offsetMinutes, timeZone }: Clock) {
  const at = (value: Time) => new Date((Number(value) - offsetMinutes * 60) * 1000)
  const time = (date: Date) =>
    date.toLocaleTimeString(hour12 ? 'en-US' : 'en-GB', {
      hour: hour12 ? 'numeric' : '2-digit',
      minute: '2-digit',
      hour12,
      timeZone,
    })
  const day = (date: Date) =>
    date.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', timeZone })

  return {
    localization: { timeFormatter: (value: Time) => `${day(at(value))} ${time(at(value))}` },
    tickMarkFormatter: (value: Time, type: TickMarkType) => {
      const date = at(value)
      switch (type) {
        case TickMarkType.Year:
          return date.toLocaleDateString('en-GB', { year: 'numeric', timeZone })
        case TickMarkType.Month:
          return date.toLocaleDateString('en-GB', { month: 'short', timeZone })
        case TickMarkType.DayOfMonth:
          return day(date)
        default:
          return time(date)
      }
    },
  }
}

/** Written the way a broker offset is usually spoken: UTC+3, UTC-4:30. */
function utcOffsetLabel(minutes: number): string {
  const sign = minutes < 0 ? '-' : '+'
  const hours = Math.floor(Math.abs(minutes) / 60)
  const rest = Math.abs(minutes) % 60
  return `UTC${sign}${hours}${rest ? `:${String(rest).padStart(2, '0')}` : ''}`
}

function LocalReplay({ trade, timeframe }: { trade: TradeDetail; timeframe: string }) {
  const { settings, hour12 } = useSettings()
  const container = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const priceLines = useRef<IPriceLine[]>([])
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null)

  const { data, isLoading, isError } = useQuery({
    queryKey: ['candles', trade.id, timeframe],
    queryFn: () =>
      api.get<CandleResponse>('/mt5/candles', { trade_id: trade.id, timeframe }),
  })

  // Which clock to label the axis with. Reading the trade in the user's own
  // timezone needs the broker's offset, and until a terminal has reported one
  // there is nothing to convert *from*: guessing would put every label an hour
  // or three out while looking authoritative, so the broker's clock stands.
  const { data: accounts = [] } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => api.get<Account[]>('/accounts'),
    staleTime: 300_000,
  })
  const brokerOffset = accounts.find((a) => a.id === trade.account_id)
    ?.broker_utc_offset_minutes
  const wantsLocal = settings.general.chart_times === 'local'
  const local = wantsLocal && brokerOffset !== null && brokerOffset !== undefined
  const clock: Clock = local
    ? { hour12, offsetMinutes: brokerOffset, timeZone: settings.general.timezone }
    : { hour12, offsetMinutes: 0, timeZone: 'UTC' }

  useEffect(() => {
    if (!container.current) return

    const styles = getComputedStyle(document.documentElement)
    const token = (name: string, fallback: string) =>
      styles.getPropertyValue(name).trim() || fallback

    const chart = createChart(container.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: token('--tz-text-muted', '#98a1b8'),
        fontFamily: styles.getPropertyValue('font-family') || 'Inter, sans-serif',
        attributionLogo: false,
      },
      grid: {
        vertLines: { color: token('--tz-grid', '#1f2532') },
        horzLines: { color: token('--tz-grid', '#1f2532') },
      },
      rightPriceScale: { borderColor: token('--tz-border', '#232939') },
      timeScale: {
        borderColor: token('--tz-border', '#232939'),
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: { mode: CrosshairMode.Normal },
      // Both axes drag. The price one used to be pinned, which keeps the
      // candles filling the pane but leaves no way to stretch a quiet stretch
      // of the chart open far enough to see where a stop actually sat.
      // Double-clicking the price axis puts it back on auto.
      handleScale: { axisPressedMouseMove: { time: true, price: true } },
      handleScroll: { vertTouchDrag: true },
    })

    const series = chart.addSeries(CandlestickSeries, {
      upColor: token('--tz-gain', '#12b06f'),
      downColor: token('--tz-loss', '#c93a48'),
      borderUpColor: token('--tz-gain', '#12b06f'),
      borderDownColor: token('--tz-loss', '#c93a48'),
      wickUpColor: token('--tz-gain', '#12b06f'),
      wickDownColor: token('--tz-loss', '#c93a48'),
      priceFormat: { type: 'price', precision: trade.digits, minMove: 10 ** -trade.digits },
    })

    chartRef.current = chart
    seriesRef.current = series
    return () => {
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [trade.digits])

  // Applied rather than passed to createChart, so flipping the clock relabels
  // the axis in place: rebuilding the chart would drop the candles with it.
  useEffect(() => {
    const labels = axisLabels(clock)
    chartRef.current?.applyOptions({
      localization: labels.localization,
      timeScale: { tickMarkFormatter: labels.tickMarkFormatter },
    })
  }, [clock.hour12, clock.offsetMinutes, clock.timeZone, trade.digits])

  useEffect(() => {
    const series = seriesRef.current
    const chart = chartRef.current
    if (!series || !chart || !data?.candles.length) return

    // The chart paints to a canvas, so CSS custom properties have to be
    // resolved to real colours before they are handed over.
    const styles = getComputedStyle(document.documentElement)
    const token = (name: string, fallback: string) =>
      styles.getPropertyValue(name).trim() || fallback
    const gain = token('--tz-gain', '#12b06f')
    const loss = token('--tz-loss', '#c93a48')
    // Entry is deliberately not the brand colour: with a green accent it
    // would be indistinguishable from the exit line on a winning trade.
    const entry = token('--tz-entry', '#4593e8')

    for (const line of priceLines.current) series.removePriceLine(line)
    priceLines.current = []
    markers.current?.setMarkers([])

    series.setData(
      data.candles.map((candle) => ({
        time: brokerTime(candle.time),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      })),
    )

    // Entry, exit, stop and target as price lines.
    priceLines.current.push(series.createPriceLine({
      price: trade.entry_price,
      color: entry,
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: true,
      title: 'Entry',
    }))
    if (trade.exit_price !== null) {
      priceLines.current.push(series.createPriceLine({
        price: trade.exit_price,
        color: trade.net_pnl >= 0 ? gain : loss,
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: 'Exit',
      }))
    }
    if (trade.initial_stop) {
      priceLines.current.push(series.createPriceLine({
        price: trade.initial_stop,
        color: loss,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'Stop',
      }))
    }
    if (trade.initial_target) {
      priceLines.current.push(series.createPriceLine({
        price: trade.initial_target,
        color: gain,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'Target',
      }))
    }

    // Every individual fill gets an arrow so scale-ins are visible.
    markers.current = createSeriesMarkers(
      series,
      trade.executions
        .map((execution) => ({
          time: brokerTime(execution.time),
          position: execution.side === 'buy' ? ('belowBar' as const) : ('aboveBar' as const),
          color: execution.kind === 'in' ? entry : execution.profit >= 0 ? gain : loss,
          shape: execution.side === 'buy' ? ('arrowUp' as const) : ('arrowDown' as const),
          text: `${execution.kind === 'in' ? 'In' : 'Out'} ${execution.volume}`,
        }))
        .sort((a, b) => Number(a.time) - Number(b.time)),
    )

    chart.timeScale().fitContent()
  }, [data, trade])

  const hasCandles = Boolean(data?.candles.length)
  // Asked for something shorter than what was collected, which is the one
  // gap that cannot be filled by folding bars together.
  const tooShort = data?.source === 'none' && Boolean(data?.available?.length)

  return (
    <div>
      <div className="relative h-[440px] w-full">
        {/* Always mounted: lightweight-charts needs a live element to attach
            to, and the states below sit on top of it rather than replacing it. */}
        <div ref={container} className="h-full w-full" />

        {isLoading && <Skeleton className="absolute inset-0" />}

        {!isLoading && (isError || !hasCandles) && (
          <div className="absolute inset-0 flex items-center justify-center rounded-lg border border-dashed border-[var(--tz-border-strong)] bg-[var(--tz-surface)]">
            <EmptyState
              icon={<CandlestickChart size={32} strokeWidth={1.4} />}
              title={
                tooShort
                  ? `${timeframe} is shorter than the bars collected`
                  : 'No candles stored for this window'
              }
              description={
                tooShort ? (
                  <>
                    Longer timeframes are built from the {data?.available?.[0]} bars the terminal
                    sends; a shorter one cannot be, so it is left out rather than invented. Pick{' '}
                    {data?.available?.[0]} or longer.
                  </>
                ) : (
                  <>
                    The TradeZulu Expert Advisor uploads candles around each closed trade — set
                    <code className="mx-1 rounded bg-[var(--tz-surface-2)] px-1 py-0.5 text-xs">
                      UploadCandles = true
                    </code>
                    on it, or switch to the TradingView tab above.
                  </>
                )
              }
            />
          </div>
        )}
      </div>

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--tz-text-muted)]">
        <Legend color="var(--tz-entry)" label={`Entry ${price(trade.entry_price, trade.digits)}`} />
        {trade.exit_price !== null && (
          <Legend
            color={trade.net_pnl >= 0 ? 'var(--tz-gain)' : 'var(--tz-loss)'}
            label={`Exit ${price(trade.exit_price, trade.digits)}`}
          />
        )}
        {trade.initial_stop && (
          <Legend color="var(--tz-loss)" label={`Stop ${price(trade.initial_stop, trade.digits)}`} />
        )}
        {trade.initial_target && (
          <Legend
            color="var(--tz-gain)"
            label={`Target ${price(trade.initial_target, trade.digits)}`}
          />
        )}
        {hasCandles && (
          <span className="ml-auto">
            {data?.candles.length} candles ·{' '}
            {data?.source === 'local' ? 'as recorded' : `built from ${data?.source}`} ·{' '}
            <span
              title={
                local
                  ? `The broker's clock runs ${utcOffsetLabel(brokerOffset)}; times are ` +
                    'converted to your timezone. The candles themselves are untouched.'
                  : brokerOffset === null || brokerOffset === undefined
                    ? 'Times are the broker’s own clock. No terminal has reported how ' +
                      'far it runs from UTC yet, so it cannot be converted.'
                    : `Times are the broker’s own clock (${utcOffsetLabel(brokerOffset)}), ` +
                      'the same as in MetaTrader.'
              }
            >
              {local ? settings.general.timezone.replace(/_/g, ' ') : 'broker time'}
              {!local && wantsLocal && ' (offset unknown)'}
            </span>
          </span>
        )}
      </div>
    </div>
  )
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="h-0.5 w-3.5 rounded" style={{ backgroundColor: color }} />
      {label}
    </span>
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
        <strong>{dateTime(trade.closed_at ?? trade.opened_at)}</strong>. Replay
        opens on the trade itself, with your fills marked.
      </p>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--tz-text-muted)]">
        <span>
          Entry {price(trade.entry_price, trade.digits)}
          {trade.exit_price !== null && ` → exit ${price(trade.exit_price, trade.digits)}`}
        </span>
        {trade.initial_stop && <span>Stop {price(trade.initial_stop, trade.digits)}</span>}
        {trade.initial_target && <span>Target {price(trade.initial_target, trade.digits)}</span>}
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
