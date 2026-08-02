import { Link } from 'react-router-dom'
import { num } from '../lib/format'
import type { ZuluScore } from '../lib/types'
import { ScoreRadar } from './charts'
import { Card, CardHeader, Progress } from './ui'

const AXIS_LABELS: Record<string, string> = {
  win_rate: 'Win rate',
  profit_factor: 'Profit factor',
  avg_win_loss: 'Avg win/loss',
  loss_consistency: 'Even losses',
  recovery_factor: 'Recovery',
  consistency: 'Consistency',
}

const SCORE_BANDS = [
  { min: 80, label: 'Excellent', color: 'var(--tz-gain)' },
  { min: 60, label: 'Solid', color: 'var(--tz-entry)' },
  { min: 40, label: 'Developing', color: '#eab308' },
  { min: 0, label: 'Needs work', color: 'var(--tz-loss)' },
]

export function ZuluScoreCard({ score }: { score: ZuluScore }) {
  // Withheld rather than zero: the score is a single read on one account, and
  // across several it is not a smaller number, it is not a number.
  if (score.score === null) {
    return (
      <Card className="flex flex-col">
        <CardHeader
          title="Zulu Score"
          hint="Six weighted components, each scored 0-100 against a target you set in Settings: win rate, profit factor, average win/loss, how even the losses were, recovery factor and consistency."
        />
        <div className="flex flex-1 items-center justify-center px-6 py-12 text-center text-sm text-[var(--tz-text-muted)]">
          The score rates one account. Pick an account above to see it.
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
        hint="Six weighted components, each scored 0-100 against a target you set in Settings: win rate, profit factor, average win/loss, how even the losses were, recovery factor and consistency."
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
        {Object.entries(score.components).map(([key, value]) => (
          <div key={key} className="flex items-center gap-3">
            <span className="w-28 shrink-0 text-xs text-[var(--tz-text-muted)]">
              {AXIS_LABELS[key] ?? key}
            </span>
            <div className="flex-1">
              <Progress value={value ?? 0} color={value === null ? 'var(--tz-flat)' : band.color} />
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
