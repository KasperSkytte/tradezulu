import { Link } from 'react-router-dom'
import { num } from '../lib/format'
import type { ZuluScore } from '../lib/types'
import { ScoreRadar } from './charts'
import { Card, CardHeader, Progress } from './ui'

const AXIS_LABELS: Record<string, string> = {
  win_rate: 'Win rate',
  profit_factor: 'Profit factor',
  avg_win_loss: 'Avg win/loss',
  max_drawdown: 'Drawdown',
  loss_consistency: 'Even losses',
  recovery_factor: 'Recovery',
  consistency: 'Consistency',
}

const SCORE_HINT =
  'Each component you switch on is scored 0-100 against a target you set in Settings, ' +
  'then averaged by weight: win rate, profit factor, average win/loss, drawdown from the ' +
  'high-water mark, how even the losses were, recovery factor and consistency.'

const SCORE_BANDS = [
  { min: 80, label: 'Excellent', color: 'var(--tz-gain)' },
  { min: 60, label: 'Solid', color: 'var(--tz-entry)' },
  { min: 40, label: 'Developing', color: '#eab308' },
  { min: 0, label: 'Needs work', color: 'var(--tz-loss)' },
]

export function ZuluScoreCard({ score }: { score: ZuluScore }) {
  // Withheld rather than zero. Across several accounts it is not a smaller
  // number, it is not a number; with every component switched off there is
  // nothing it could be a number about. Neither is a bad score.
  if (score.score === null) {
    const offByChoice = /no components/.test(score.unavailable_reason ?? '')
    return (
      <Card className="flex flex-col">
        <CardHeader title="Zulu Score" hint={SCORE_HINT} />
        <div className="flex flex-1 flex-col items-center justify-center gap-2 px-6 py-12 text-center text-sm text-[var(--tz-text-muted)]">
          {offByChoice ? (
            <>
              <span>Every component is switched off, so there is nothing to score.</span>
              <Link to="/settings#score" className="text-xs underline">
                Turn some on
              </Link>
            </>
          ) : (
            <span>The score rates one account. Pick an account above to see it.</span>
          )}
        </div>
      </Card>
    )
  }

  const value = score.score
  const band = SCORE_BANDS.find((entry) => value >= entry.min) ?? SCORE_BANDS.at(-1)!
  const radarData = Object.entries(score.components)
    .filter(([, value]) => value !== null)
    .map(([key, value]) => ({
      axis: AXIS_LABELS[key] ?? key,
      value: value ?? 0,
      target: 100,
    }))

  return (
    <Card className="flex flex-col">
      <CardHeader
        title="Zulu Score"
        hint={SCORE_HINT}
        action={
          <Link
            to="/settings#score"
            className="text-xs text-[var(--tz-text-muted)] hover:text-[var(--tz-text)]"
          >
            Tune
          </Link>
        }
      />

      {radarData.length >= 3 ? (
        <ScoreRadar data={radarData} />
      ) : (
        <div className="flex h-[240px] items-center justify-center text-sm text-[var(--tz-text-muted)]">
          Not enough data to plot the components yet
        </div>
      )}

      <div className="mt-1 flex items-baseline justify-center gap-2">
        <span className="tabular text-3xl font-semibold" style={{ color: band.color }}>
          {num(value, 1)}
        </span>
        <span className="text-sm text-[var(--tz-text-muted)]">/ 100 · {band.label}</span>
      </div>

      {!score.sufficient && (
        <p className="mt-2 text-center text-xs text-[var(--tz-text-faint)]">
          Based on {score.sample_size ?? 0} trades — the score settles down after about{' '}
          {score.min_trades}.
        </p>
      )}

      <div className="mt-4 space-y-2 border-t border-[var(--tz-border)] pt-3">
        {Object.entries(score.components)
          // A component with no weight is not a component: it contributes
          // nothing to the number above, so listing it would explain a score
          // it had no part in.
          .filter(([key]) => (score.weights?.[key] ?? 1) > 0)
          .map(([key, value]) => (
            <div key={key} className="flex items-center gap-3">
              <span className="w-28 shrink-0 text-xs text-[var(--tz-text-muted)]">
                {AXIS_LABELS[key] ?? key}
              </span>
              <div className="flex-1">
                <Progress
                  value={value ?? 0}
                  color={value === null ? 'var(--tz-flat)' : band.color}
                />
              </div>
              <span className="tabular w-8 shrink-0 text-right text-xs">
                {value === null ? '—' : Math.round(value)}
              </span>
            </div>
          ))}
      </div>
    </Card>
  )
}
