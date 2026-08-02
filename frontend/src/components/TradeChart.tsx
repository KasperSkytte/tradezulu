/**
 * Trade replay.
 *
 * Two providers, both free:
 *  - "local" draws candles TradeZulu already holds (pushed by the Expert
 *    Advisor) with the real entry, exit, stop and
 *    target marked on the price scale. This is the one that can show *your*
 *    fills, so it is the default.
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
import { useIsDark, useSettings } from '../lib/settings'
import { price } from '../lib/format'
import type { Account, BrokerList, CandleResponse, TradeDetail } from '../lib/types'
import { EmptyState, SegmentedControl, Skeleton } from './ui'

const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1']

const TV_INTERVAL: Record<string, string> = {
  M1: '1',
  M5: '5',
  M15: '15',
  M30: '30',
  H1: '60',
  H4: '240',
  D1: 'D',
}

export function TradeChart({ trade }: { trade: TradeDetail }) {
  const { settings } = useSettings()
  const [provider, setProvider] = useState<'local' | 'tradingview'>(settings.charts.provider)
  const [timeframe, setTimeframe] = useState(settings.charts.default_timeframe || 'M15')

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <SegmentedControl
          size="sm"
          value={provider}
          onChange={setProvider}
          options={[
            { value: 'local', label: 'Replay', title: 'Candles stored by TradeZulu' },
            { value: 'tradingview', label: 'TradingView', title: 'Free TradingView widget' },
          ]}
        />
        <SegmentedControl
          size="sm"
          value={timeframe}
          onChange={setTimeframe}
          options={TIMEFRAMES.map((value) => ({ value, label: value }))}
        />
      </div>

      {provider === 'local' ? (
        <LocalReplay trade={trade} timeframe={timeframe} />
      ) : (
        <TradingViewChart trade={trade} timeframe={timeframe} />
      )}
    </div>
  )
}

/* --------------------------------------------------------------------- */

function LocalReplay({ trade, timeframe }: { trade: TradeDetail; timeframe: string }) {
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
      handleScale: { axisPressedMouseMove: { time: true, price: false } },
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
        time: (Date.parse(candle.time) / 1000) as Time,
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
          time: (Date.parse(execution.time) / 1000) as Time,
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
              title="No candles stored for this window"
              description={
                <>
                  The TradeZulu Expert Advisor uploads candles around each closed trade — set
                  <code className="mx-1 rounded bg-[var(--tz-surface-2)] px-1 py-0.5 text-xs">
                    UploadCandles = true
                  </code>
                  on it, or switch to the TradingView tab above.
                </>
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
            {data?.candles.length} candles · source: {data?.source}
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
  }, [symbol, timeframe, settings.general.timezone, dark])

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
