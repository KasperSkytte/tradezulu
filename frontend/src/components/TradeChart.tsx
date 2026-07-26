/**
 * Trade replay.
 *
 * Two providers, both free:
 *  - "local" draws candles TradeZulu already holds (pushed by the Expert
 *    Advisor or pulled from the bridge) with the real entry, exit, stop and
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
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts'
import { CandlestickChart, ExternalLink } from 'lucide-react'
import { api } from '../lib/api'
import { useSettings } from '../lib/settings'
import { price } from '../lib/format'
import type { CandleResponse, TradeDetail } from '../lib/types'
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
    const accent = token('--color-zulu-400', '#8f78ff')

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
    series.createPriceLine({
      price: trade.entry_price,
      color: accent,
      lineWidth: 2,
      lineStyle: LineStyle.Solid,
      axisLabelVisible: true,
      title: 'Entry',
    })
    if (trade.exit_price !== null) {
      series.createPriceLine({
        price: trade.exit_price,
        color: trade.net_pnl >= 0 ? gain : loss,
        lineWidth: 2,
        lineStyle: LineStyle.Solid,
        axisLabelVisible: true,
        title: 'Exit',
      })
    }
    if (trade.initial_stop) {
      series.createPriceLine({
        price: trade.initial_stop,
        color: loss,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'Stop',
      })
    }
    if (trade.initial_target) {
      series.createPriceLine({
        price: trade.initial_target,
        color: gain,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: 'Target',
      })
    }

    // Every individual fill gets an arrow so scale-ins are visible.
    createSeriesMarkers(
      series,
      trade.executions
        .map((execution) => ({
          time: (Date.parse(execution.time) / 1000) as Time,
          position: execution.side === 'buy' ? ('belowBar' as const) : ('aboveBar' as const),
          color: execution.kind === 'in' ? accent : execution.profit >= 0 ? gain : loss,
          shape: execution.side === 'buy' ? ('arrowUp' as const) : ('arrowDown' as const),
          text: `${execution.kind === 'in' ? 'In' : 'Out'} ${execution.volume}`,
        }))
        .sort((a, b) => Number(a.time) - Number(b.time)),
    )

    chart.timeScale().fitContent()
  }, [data, trade])

  if (isLoading) return <Skeleton className="h-[380px]" />

  if (isError || !data?.candles.length) {
    return (
      <div className="flex h-[380px] items-center justify-center rounded-lg border border-dashed border-[var(--tz-border-strong)]">
        <EmptyState
          icon={<CandlestickChart size={32} strokeWidth={1.4} />}
          title="No candles stored for this window"
          description={
            <>
              The TradeZuluSync Expert Advisor uploads candles around each closed trade — set
              <code className="mx-1 rounded bg-[var(--tz-surface-2)] px-1 py-0.5 text-xs">
                UploadCandles = true
              </code>
              on it, or switch to the TradingView tab above.
            </>
          }
        />
      </div>
    )
  }

  return (
    <div>
      <div ref={container} className="h-[380px] w-full" />
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--tz-text-muted)]">
        <Legend color="var(--color-zulu-400)" label={`Entry ${price(trade.entry_price, trade.digits)}`} />
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
        <span className="ml-auto">{data.candles.length} candles · source: {data.source}</span>
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

  const mapped = settings.charts.symbol_map[trade.symbol]
  const symbol = mapped || `${settings.charts.tradingview_prefix}${trade.symbol}`

  useEffect(() => {
    const element = container.current
    if (!element) return
    element.innerHTML = ''

    const dark = document.documentElement.classList.contains('dark')
    const widget = document.createElement('div')
    widget.className = 'tradingview-widget-container__widget h-full w-full'
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
  }, [symbol, timeframe, settings.general.timezone])

  return (
    <div>
      <div className="tradingview-widget-container h-[420px] w-full" ref={container} />
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
