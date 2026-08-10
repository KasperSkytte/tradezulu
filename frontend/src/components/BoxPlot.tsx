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

import { isFew, type Spread } from '../lib/types'

/** One row: a distribution, what to call it, and how to write its numbers. */
export type BoxRow = Spread & { key: string; label: string }

/** A plain pixel-ish coordinate space, scaled to the card by the viewBox.
 *  Everything below is in these units: a row's height, the axis strip under
 *  the last one, and the label column down the left. */
const WIDTH = 640
const ROW = 46
const AXIS = 24
const LABELS = 104

export function BoxPlot({
  series,
  format,
  formatTick,
}: {
  series: BoxRow[]
  /** Whatever unit the page is currently answering in -- R, money, percent. */
  format: (value: number) => string
  /** The same unit, written for a ruler: coarser and unsigned, because
   *  "+$1,000.00" eight times across a card is a smear rather than a scale. */
  formatTick?: (value: number) => string
}) {
  if (!series.length) return null

  // One scale across every row, or the boxes cannot be compared -- which is
  // the entire reason they are stacked on top of each other.
  //
  // Whiskers only. A single trade at 15R is why the outliers are separated
  // from the box in the first place, and letting one set the axis squashes
  // every box into the left tenth of the card -- hiding the distribution to
  // make room for the exception to it. The ones that fall outside are drawn
  // against the edge instead, and the count in the tooltip still has them.
  const all = series.flatMap((s) => (isFew(s) ? s.points : [s.min, s.max]))
  const low = Math.min(...all, 0)
  const high = Math.max(...all, 0)
  const pad = (high - low) * 0.06 || 1
  const from = low - pad
  const to = high + pad

  const plot = WIDTH - LABELS - 12
  const x = (value: number) => LABELS + ((value - from) / (to - from)) * plot

  const height = series.length * ROW + AXIS
  // Round numbers read better than a computed scale, but not every round
  // number: across a wide range they collide into a smear, so the step is the
  // next 1, 2 or 5 of the right size up from an eighth of the range. It has to
  // hold for half an R and for three thousand dollars, which a fixed list of
  // steps does not -- money ran off the end of one and drew fourteen labels
  // over each other.
  const rough = (to - from) / 8
  const magnitude = 10 ** Math.floor(Math.log10(rough))
  const step = ([1, 2, 5].find((n) => n * magnitude >= rough) ?? 10) * magnitude
  // Counted out rather than accumulated, so the zero tick is exactly zero.
  // Adding the step repeatedly drifts (-1.4e-16 after a few tenths), and
  // Math.ceil returns negative zero for anything in (-1, 0) -- both of which
  // Intl spells "-0.00", labelling the one gridline that means something, the
  // line between a trade that paid and one that did not, as a small loss.
  const ticks: number[] = []
  for (let i = Math.ceil(from / step); i * step <= to; i += 1) ticks.push(i === 0 ? 0 : i * step)

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
            {(formatTick ?? format)(tick)}
          </text>
        </g>
      ))}

      {series.map((s, index) => {
        const mid = index * ROW + ROW / 2
        const box = 17
        // Losers sit left of zero and winners right of it, so colouring by
        // where the middle falls matches what the eye already read.
        const middle = isFew(s) ? s.points[Math.floor(s.points.length / 2)] : s.median
        const colour =
          middle > 0 ? 'var(--tz-gain)' : middle < 0 ? 'var(--tz-loss)' : 'var(--tz-flat)'

        const heading = (
          <>
            <text x={0} y={mid - 1} fill="var(--tz-text)" style={{ fontSize: 12 }}>
              {s.label}
            </text>
            <text x={0} y={mid + 12} fill="var(--tz-text-faint)" style={{ fontSize: 10 }}>
              {s.count === 1 ? '1 trade' : `${s.count} trades`}
            </text>
          </>
        )

        // Two trades have quartiles the way two people have an average height:
        // the arithmetic works and describes nobody. Drawn as the trades they
        // are, on the same axis as the boxes, because leaving the row out
        // altogether read as "no winners" on a day that had two.
        if (isFew(s)) {
          return (
            <g key={s.key}>
              {heading}
              {s.points.map((value, at) => (
                <circle key={at} cx={x(value)} cy={mid} r={3.4} fill={colour} fillOpacity={0.75} />
              ))}
              <title>
                {`${s.label}: ${s.count === 1 ? '1 trade' : `${s.count} trades`}, at ` +
                  `${s.points.map(format).join(', ')} -- too few to draw a box`}
              </title>
            </g>
          )
        }

        return (
          <g key={s.key}>
            {heading}

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

            {/* Anything past the axis is pinned to its edge and drawn hollow,
                so "there are trades out this way" survives without the scale
                being handed over to them. */}
            {s.outliers.map((value, at) => {
              const beyond = value < from || value > to
              return (
                <circle
                  key={at}
                  cx={x(Math.min(Math.max(value, from), to))}
                  cy={mid}
                  r={2.4}
                  fill={beyond ? 'none' : colour}
                  stroke={colour}
                  strokeWidth={beyond ? 1.2 : 0}
                  fillOpacity={0.55}
                />
              )
            })}

            <title>
              {`${s.label}: median ${format(s.median)}, middle half ${format(s.q1)} to ` +
                `${format(s.q3)}, reaching ${format(s.min)} to ${format(s.max)}` +
                (s.outliers.length ? `, ${s.outliers.length} beyond that` : '')}
            </title>
          </g>
        )
      })}
    </svg>
  )
}
