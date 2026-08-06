/**
 * Distributions, drawn as box plots.
 *
 * An average is one number standing in for a shape, and the shape is the part
 * worth seeing: whether the winners cluster or come from three lucky trades,
 * whether the losses sit tight against the stop or scatter past it. Two
 * strategies with the same expectancy can look nothing alike here, and the one
 * that is survivable is the one with the tighter left tail.
 *
 * Drawn by hand rather than with the charting library: a box plot is five
 * numbers and a line, and every library route to one goes through stacked bars
 * with invisible segments, which is more code than the SVG and harder to read.
 */

import { num } from '../lib/format'

export type Distribution = {
  key: string
  label: string
  hint: string
  count: number
  min: number
  q1: number
  median: number
  q3: number
  max: number
  mean: number | null
  outliers: number[]
}

/** A plain pixel-ish coordinate space, scaled to the card by the viewBox.
 *  Everything below is in these units: a row's height, the axis strip under
 *  the last one, and the label column down the left. */
const WIDTH = 640
const ROW = 58
const AXIS = 26
const LABELS = 118

export function BoxPlot({ series }: { series: Distribution[] }) {
  if (!series.length) return null

  // One scale across every row, or the boxes cannot be compared -- which is
  // the entire reason they are stacked on top of each other.
  const all = series.flatMap((s) => [s.min, s.max, ...s.outliers])
  const low = Math.min(...all, 0)
  const high = Math.max(...all, 0)
  const pad = (high - low) * 0.06 || 1
  const from = low - pad
  const to = high + pad

  const plot = WIDTH - LABELS - 12
  const x = (value: number) => LABELS + ((value - from) / (to - from)) * plot

  const height = series.length * ROW + AXIS
  // Whole numbers of R read better than a computed scale, but not every whole
  // number: across a wide range they collide into a smear, so the step grows
  // until about eight labels fit.
  const step = [1, 2, 5, 10, 20, 50].find((n) => (to - from) / n <= 8) ?? 100
  const ticks: number[] = []
  for (let t = Math.ceil(from / step) * step; t <= to; t += step) ticks.push(t)

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${height}`}
      className="h-auto w-full"
      role="img"
      aria-label="Distribution of planned and realised R"
    >
      {/* Gridlines and the zero line, which is the one that means something:
          left of it the trade lost, right of it it paid. */}
      {ticks.map((tick) => (
        <g key={tick}>
          <line
            x1={x(tick)}
            x2={x(tick)}
            y1={0}
            y2={series.length * ROW}
            stroke="var(--tz-grid)"
            strokeWidth={tick === 0 ? 1.2 : 0.6}
          />
          <text
            x={x(tick)}
            y={height - 8}
            textAnchor="middle"
            fill="var(--tz-text-faint)"
            style={{ fontSize: 11 }}
          >
            {tick}R
          </text>
        </g>
      ))}

      {series.map((s, index) => {
        const mid = index * ROW + ROW / 2
        const box = 22
        // Losers sit left of zero and winners right of it, so colouring by
        // where the median falls matches what the eye already read.
        const colour =
          s.median > 0 ? 'var(--tz-gain)' : s.median < 0 ? 'var(--tz-loss)' : 'var(--tz-flat)'

        return (
          <g key={s.key}>
            <text x={0} y={mid - 2} fill="var(--tz-text)" style={{ fontSize: 13 }}>
              {s.label}
            </text>
            <text x={0} y={mid + 14} fill="var(--tz-text-faint)" style={{ fontSize: 11 }}>
              {s.count} trades
            </text>

            {/* Whiskers to the furthest trade that is not an outlier. */}
            <line x1={x(s.min)} x2={x(s.max)} y1={mid} y2={mid} stroke={colour} strokeWidth={1.4} />
            {[s.min, s.max].map((end) => (
              <line
                key={end}
                x1={x(end)}
                x2={x(end)}
                y1={mid - box / 3}
                y2={mid + box / 3}
                stroke={colour}
                strokeWidth={1.4}
              />
            ))}

            {/* The middle half of every trade. */}
            <rect
              x={x(s.q1)}
              y={mid - box / 2}
              width={Math.max(x(s.q3) - x(s.q1), 1.5)}
              height={box}
              fill={colour}
              fillOpacity={0.18}
              stroke={colour}
              strokeWidth={1.4}
            />
            <line
              x1={x(s.median)}
              x2={x(s.median)}
              y1={mid - box / 2}
              y2={mid + box / 2}
              stroke={colour}
              strokeWidth={2.6}
            />

            {s.outliers.map((value, at) => (
              <circle key={at} cx={x(value)} cy={mid} r={2.4} fill={colour} fillOpacity={0.55} />
            ))}

            <title>
              {`${s.label}: median ${num(s.median, 2)}R, middle half ${num(s.q1, 2)}R to ` +
                `${num(s.q3, 2)}R, reaching ${num(s.min, 2)}R to ${num(s.max, 2)}R` +
                (s.outliers.length ? `, ${s.outliers.length} beyond that` : '')}
            </title>
          </g>
        )
      })}
    </svg>
  )
}
