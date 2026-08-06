/**
 * The replay, drawn on your trade rather than beside it.
 *
 * The other two tabs each give up one half of what a replay is for. Replay
 * knows the trade and marks it, but has no drawing tools. The TradingView
 * embed has every tool and no idea a trade happened -- which, as the point of
 * a replay is to look at *your* entry, makes the tools academic.
 *
 * This is both. KLineChart (Apache-2.0, no dependencies) anchors overlays to an
 * exact timestamp and price rather than to a bar, so the position is drawn
 * where it actually happened: a box from entry to exit, the risk you took
 * shaded below it, the target above, and every fill on the minute it filled.
 * Its own drawing tools sit on top of that, on the same canvas.
 *
 * The candles are the ones TradeZulu already holds, so this needs no third
 * party to have heard of your broker's symbol.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { dispose, init, registerOverlay } from 'klinecharts'
import type { Chart, KLineData, Period } from 'klinecharts'
import { CandlestickChart, Eraser } from 'lucide-react'
import { api } from '../lib/api'
import { useIsDark, useSettings } from '../lib/settings'
import { price as formatPrice } from '../lib/format'
import type { Account, CandleResponse, TradeDetail } from '../lib/types'
import { EmptyState, SegmentedControl, Skeleton } from './ui'

const PERIODS: Record<string, Period> = {
  M1: { type: 'minute', span: 1 },
  M5: { type: 'minute', span: 5 },
  M15: { type: 'minute', span: 15 },
  M30: { type: 'minute', span: 30 },
  H1: { type: 'hour', span: 1 },
  H4: { type: 'hour', span: 4 },
  D1: { type: 'day', span: 1 },
  W1: { type: 'week', span: 1 },
}

/** How long one bar lasts, for working out how much to show at once. */
const BAR_MILLIS: Record<string, number> = {
  M1: 60_000,
  M5: 300_000,
  M15: 900_000,
  M30: 1_800_000,
  H1: 3_600_000,
  H4: 14_400_000,
  D1: 86_400_000,
  W1: 604_800_000,
}

/** The tools offered, and what KLineChart calls them. */
const TOOLS: [label: string, overlay: string, title: string][] = [
  ['Trend', 'segment', 'Draw a line between two points'],
  ['Ray', 'rayLine', 'A line that carries on past the second point'],
  ['Horizontal', 'horizontalStraightLine', 'A level across the whole chart'],
  ['Fib', 'fibonacciLine', 'Fibonacci retracement between two points'],
  ['Note', 'simpleAnnotation', 'Pin a note to a bar'],
]

/** What the trade overlay is handed, beyond its points. */
type TradeExtras = {
  hasStop: boolean
  hasTarget: boolean
  won: boolean
  colors: { gain: string; loss: string; entry: string; text: string }
}

/**
 * The position itself.
 *
 * Registered once, drawn from four points: entry and exit at their real times
 * and prices, and -- so their heights arrive already converted to pixels --
 * the stop and the target at the entry's time. Asking for them as points is
 * what keeps this free of any coordinate arithmetic of its own.
 */
registerOverlay<TradeExtras>({
  name: 'tradezulu-position',
  // Created in code, never drawn by hand: one step, already complete.
  totalStep: 1,
  needDefaultPointFigure: false,
  needDefaultXAxisFigure: false,
  needDefaultYAxisFigure: false,
  createPointFigures: ({ coordinates, overlay }) => {
    const [entry, exit, ...rest] = coordinates
    if (!entry || !exit) return []
    const extra = overlay.extendData
    if (!extra) return []
    const { hasStop, hasTarget, won, colors } = extra

    const stop = hasStop ? rest.shift() : undefined
    const target = hasTarget ? rest.shift() : undefined
    const left = Math.min(entry.x, exit.x)
    // A scalp can be one bar wide; six pixels keeps it visible without
    // pretending it lasted longer than it did.
    const width = Math.max(Math.abs(exit.x - entry.x), 6)
    const band = (edge: { y: number }, color: string) => ({
      type: 'rect',
      ignoreEvent: true,
      attrs: {
        x: left,
        y: Math.min(entry.y, edge.y),
        width,
        height: Math.max(Math.abs(edge.y - entry.y), 1),
      },
      styles: { style: 'fill', color },
    })

    return [
      // What was risked, and what was being played for -- both bounded to the
      // time the position was actually open, rather than running the width of
      // the chart the way a price line has to.
      ...(target ? [band(target, `${colors.gain}2e`)] : []),
      ...(stop ? [band(stop, `${colors.loss}2e`)] : []),
      {
        type: 'line',
        ignoreEvent: true,
        attrs: { coordinates: [entry, exit] },
        styles: { color: won ? colors.gain : colors.loss, size: 2 },
      },
      {
        type: 'circle',
        ignoreEvent: true,
        attrs: { ...entry, r: 4 },
        styles: { style: 'fill', color: colors.entry },
      },
      {
        type: 'circle',
        ignoreEvent: true,
        attrs: { ...exit, r: 4 },
        styles: { style: 'fill', color: won ? colors.gain : colors.loss },
      },
    ]
  },
})

/** One fill, at the minute it filled. */
registerOverlay<{ label: string; color: string; above: boolean; family: string }>({
  name: 'tradezulu-fill',
  totalStep: 1,
  needDefaultPointFigure: false,
  needDefaultXAxisFigure: false,
  needDefaultYAxisFigure: false,
  createPointFigures: ({ coordinates, overlay }) => {
    const point = coordinates[0]
    const extra = overlay.extendData
    if (!point || !extra) return []
    const { label, color, above, family } = extra
    const tip = above ? point.y - 10 : point.y + 10
    const base = above ? point.y - 2 : point.y + 2
    return [
      {
        type: 'polygon',
        ignoreEvent: true,
        attrs: {
          coordinates: [
            { x: point.x, y: base },
            { x: point.x - 5, y: tip },
            { x: point.x + 5, y: tip },
          ],
        },
        styles: { style: 'fill', color },
      },
      {
        type: 'text',
        ignoreEvent: true,
        attrs: {
          x: point.x,
          y: above ? tip - 14 : tip + 2,
          text: label,
          align: 'center',
        },
        // Transparent, or KLineChart gives the label its default filled pill
        // and two fills a minute apart cover the candles between them.
        styles: {
          color,
          size: 11,
          family,
          backgroundColor: 'transparent',
          paddingLeft: 0,
          paddingRight: 0,
          paddingTop: 0,
          paddingBottom: 0,
        },
      },
    ]
  },
})

export function KLineReplay({ trade, timeframe }: { trade: TradeDetail; timeframe: string }) {
  const container = useRef<HTMLDivElement>(null)
  const chartRef = useRef<Chart | null>(null)
  const { settings, hour12 } = useSettings()
  const dark = useIsDark()
  const [tool, setTool] = useState('')

  // Same query key as the other replay, so switching tabs re-uses the bars
  // rather than asking for them again.
  const { data, isLoading, isError } = useQuery({
    queryKey: ['candles', trade.id, timeframe],
    queryFn: () => api.get<CandleResponse>('/mt5/candles', { trade_id: trade.id, timeframe }),
  })

  const { data: accounts = [] } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => api.get<Account[]>('/accounts'),
    staleTime: 300_000,
  })
  const brokerOffset = accounts.find((a) => a.id === trade.account_id)?.broker_utc_offset_minutes
  const local =
    settings.general.times === 'local' && brokerOffset !== null && brokerOffset !== undefined
  // Same rule as the other tab: the bars keep the broker's clock and only the
  // labels move, so a fill never leaves the bar it happened on.
  const shiftMinutes = local ? brokerOffset : 0
  const zone = local ? settings.general.timezone : 'UTC'

  const bars: KLineData[] = useMemo(
    () =>
      (data?.candles ?? []).map((candle) => ({
        timestamp: brokerEpoch(candle.time),
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
        volume: candle.volume,
      })),
    [data],
  )

  useEffect(() => {
    const element = container.current
    if (!element || !bars.length) return

    const styles = getComputedStyle(document.documentElement)
    const token = (name: string, fallback: string) =>
      styles.getPropertyValue(name).trim() || fallback
    const gain = token('--tz-gain', '#12b06f')
    const loss = token('--tz-loss', '#c93a48')
    const entry = token('--tz-entry', '#4593e8')
    const grid = token('--tz-grid', '#1f2532')
    const border = token('--tz-border', '#232939')
    const text = token('--tz-text-muted', '#98a1b8')
    // KLineChart ships its own serif stack, which looked like a different
    // application bolted into the page. Anything drawn to a canvas has to be
    // told the font explicitly -- it inherits nothing from the stylesheet.
    const family = styles.getPropertyValue('font-family').trim() || 'Inter, sans-serif'

    const chart = init(element, {
      styles: {
        grid: { horizontal: { color: grid }, vertical: { color: grid } },
        candle: {
          bar: {
            upColor: gain, downColor: loss, noChangeColor: text,
            upBorderColor: gain, downBorderColor: loss, noChangeBorderColor: text,
            upWickColor: gain, downWickColor: loss, noChangeWickColor: text,
          },
          // No last-price line. It marks where the instrument is *now*, which
          // has nothing to do with a trade taken in the past, and it draws
          // straight across the position it is meant to be showing.
          priceMark: { last: { show: false } },
          tooltip: {
            title: { color: text, family, size: 12 },
            legend: { color: text, family, size: 12 },
          },
        },
        xAxis: {
          axisLine: { color: border },
          tickLine: { color: border },
          tickText: { color: text, family, size: 11 },
        },
        yAxis: {
          axisLine: { color: border },
          tickLine: { color: border },
          tickText: { color: text, family, size: 11 },
        },
        crosshair: {
          horizontal: { line: { color: text }, text: { backgroundColor: border, family, size: 11 } },
          vertical: { line: { color: text }, text: { backgroundColor: border, family, size: 11 } },
        },
        overlay: { point: { color: entry, borderColor: `${entry}55` }, text: { family } },
      },
      formatter: {
        // The bars are the broker's wall clock; this is the only place that
        // decides how to write one down. Same arrangement as the other tab.
        formatDate: ({ timestamp, type }) => {
          const at = new Date(timestamp - shiftMinutes * 60_000)
          const clock = hour12 ? 'en-US' : 'en-GB'
          const time = at.toLocaleTimeString(clock, {
            hour: hour12 ? 'numeric' : '2-digit',
            minute: '2-digit',
            hour12,
            timeZone: zone,
          })
          const day = at.toLocaleDateString('en-GB', {
            day: 'numeric', month: 'short', timeZone: zone,
          })
          return type === 'xAxis' ? time : `${day} ${time}`
        },
      },
    })
    if (!chart) return
    chartRef.current = chart

    chart.setSymbol({ ticker: trade.symbol, pricePrecision: trade.digits })
    chart.setPeriod(PERIODS[timeframe] ?? PERIODS.M15)
    const colors = { gain, loss, entry, text }
    const openedAt = brokerEpoch(trade.opened_at)
    const closedAt = trade.closed_at ? brokerEpoch(trade.closed_at) : openedAt
    const exitPrice = trade.exit_price ?? trade.entry_price

    /**
     * Open on the trade.
     *
     * A chart of the right symbol showing the wrong hours is the one failure
     * the TradingView tab cannot escape, and there is no reason to inherit it
     * here.
     */
    const frame = () => {
      const barMs = BAR_MILLIS[timeframe] ?? BAR_MILLIS.M15
      const held = Math.max(closedAt - openedAt, barMs)
      // The position, plus the configured context either side of it. Always the
      // whole position: a chart of a trade that does not fit the trade on it is
      // not a chart of the trade. Everything beyond this is still loaded and one
      // scroll away.
      const context = Math.max(0, settings.charts.zoom_hours ?? 2) * 3_600_000
      const wanted = Math.min(
        Math.max(Math.round((held + context * 2) / barMs), 20),
        bars.length,
      )
      chart.setBarSpace(Math.max(element.clientWidth / wanted, 2))
      // Room past the newest bar. A trade closed minutes ago has no candles
      // after it to be padded with, and would otherwise sit under the price
      // axis.
      chart.setOffsetRightDistance(70)
      // Padded by a share of what is on screen rather than of the trade, so the
      // exit lands in the same place whether it was held seven minutes or
      // twelve hours.
      chart.scrollToTimestamp(closedAt + wanted * barMs * 0.15, 0)
    }

    chart.setDataLoader({
      // Everything there is, in one go: this is a fixed window around one
      // trade, not a feed that scrolls back for ever.
      getBars: ({ callback }) => {
        callback(bars, { backward: false, forward: false })
        // Framing has to wait for the bars to be in: the loader is async, and
        // anything set before they land is overwritten when they do.
        requestAnimationFrame(frame)
      },
    })

    chart.createOverlay({
      name: 'tradezulu-position',
      lock: true,
      // Under the drawing tools, so a line drawn over the position stays
      // visible and grabbable.
      zLevel: -1,
      points: [
        { timestamp: openedAt, value: trade.entry_price },
        { timestamp: closedAt, value: exitPrice },
        ...(trade.initial_stop ? [{ timestamp: openedAt, value: trade.initial_stop }] : []),
        ...(trade.initial_target ? [{ timestamp: openedAt, value: trade.initial_target }] : []),
      ],
      extendData: {
        hasStop: Boolean(trade.initial_stop),
        hasTarget: Boolean(trade.initial_target),
        won: trade.net_pnl >= 0,
        colors,
      },
    })

    for (const execution of trade.executions) {
      chart.createOverlay({
        name: 'tradezulu-fill',
        lock: true,
        zLevel: -1,
        points: [{ timestamp: brokerEpoch(execution.time), value: execution.price }],
        extendData: {
          label: `${execution.kind === 'in' ? 'In' : 'Out'} ${execution.volume}`,
          family,
          color:
            execution.kind === 'in' ? entry : execution.profit >= 0 ? gain : loss,
          above: execution.side === 'sell',
        },
      })
    }

    return () => {
      dispose(element)
      chartRef.current = null
    }
    // Rebuilt when any of these change: the chart is cheap to make and the
    // alternative is patching six things back into agreement by hand.
  }, [bars, trade, timeframe, dark, hour12, shiftMinutes, zone, settings.charts.zoom_hours])

  const start = (name: string) => {
    setTool(name)
    if (name) chartRef.current?.createOverlay(name)
  }

  const clear = () => {
    setTool('')
    // By name, so the position and its fills survive: they are not the user's
    // drawings and should not be swept up with them.
    for (const [, name] of TOOLS) chartRef.current?.removeOverlay({ name })
  }

  const hasCandles = bars.length > 0
  const tooShort = data?.source === 'none' && Boolean(data?.available?.length)

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <SegmentedControl
          size="sm"
          value={tool}
          onChange={start}
          options={TOOLS.map(([label, name, title]) => ({ value: name, label, title }))}
        />
        <button type="button" className="tz-btn tz-btn-ghost tz-btn-sm" onClick={clear}>
          <Eraser size={13} /> Clear
        </button>
      </div>

      <div className="relative h-[440px] w-full">
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
                  <>Pick {data?.available?.[0]} or longer — shorter bars cannot be derived.</>
                ) : (
                  <>
                    The TradeZulu Expert Advisor uploads candles around each closed trade — set
                    <code className="mx-1 rounded bg-[var(--tz-surface-2)] px-1 py-0.5 text-xs">
                      UploadCandles = true
                    </code>
                    on it.
                  </>
                )
              }
            />
          </div>
        )}
      </div>

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--tz-text-muted)]">
        <span>
          Entry {formatPrice(trade.entry_price, trade.digits)}
          {trade.exit_price !== null && ` → exit ${formatPrice(trade.exit_price, trade.digits)}`}
        </span>
        {trade.initial_stop && <span>Stop {formatPrice(trade.initial_stop, trade.digits)}</span>}
        {trade.initial_target && (
          <span>Target {formatPrice(trade.initial_target, trade.digits)}</span>
        )}
        {hasCandles && (
          <span className="ml-auto">
            {bars.length} candles · {local ? settings.general.timezone.replace(/_/g, ' ') : 'broker time'}
          </span>
        )}
      </div>
    </div>
  )
}

/**
 * A timestamp from the API as milliseconds on the broker's clock.
 *
 * Candles come back marked UTC and executions do not, though both are the same
 * clock -- so an unmarked one is read as the viewer's local time unless it is
 * said explicitly. Getting this wrong is what put the fill arrows an hour or
 * two from their own candles in the first place.
 */
function brokerEpoch(value: string): number {
  const marked = /Z$|[+-]\d\d:?\d\d$/.test(value)
  return Date.parse(marked ? value : `${value}Z`)
}
