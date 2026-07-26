# How every number is worked out

No metric in TradeZulu is a black box. This is the whole list, with the
formulas, so you can argue with them.

Everything is computed over the date range in the picker, from **closed** trades
only, in the timezone set in *Settings → General*. A trade belongs to the day it
was **closed** on.

---

## From deals to trades

MetaTrader 5 does not store trades. It stores *deals*: a position is opened by
one or more deals with `DEAL_ENTRY_IN` and closed by one or more with
`DEAL_ENTRY_OUT`, all sharing a `position_id`.

TradeZulu folds each `position_id` into one trade:

| Field | How |
|---|---|
| Direction | The type of the first entry deal — buy is long, sell is short. |
| Entry price | Volume-weighted mean of every entry deal. |
| Exit price | Volume-weighted mean of every exit deal. |
| Opened at | Time of the first entry deal. |
| Closed at | Time of the last exit deal, once the closed volume matches the opened volume. A partially closed position stays **open**. |
| Gross profit | Sum of the profit on every deal. |
| Net P&L | Gross + commission + swap + fees (each of commission and swap can be excluded in Settings). |

So scaling in and scaling out produce one row that reads the way you traded it,
and the raw deals are kept so trades can always be rebuilt.

---

## Risk and R

**R is one unit of risk**, in account currency:

```
risk = |entry − initial stop| × value-per-price-unit × lots
```

`value-per-price-unit` is `tick_value / tick_size` for the symbol, supplied by
MetaTrader. For imported files it is recovered from the realised result:
`gross_profit ÷ (price distance travelled × lots)`.

The stop is taken from the first of these that exists:

1. your manual risk override on the trade,
2. the stop on the entry order,
3. the stop the Expert Advisor remembered from the live position,
4. the fallback in *Settings → Risk* — a fixed amount, or a percentage of the
   account.

Then:

```
planned R  = |target − entry| ÷ |entry − stop|
realised R = net P&L ÷ risk
```

**Plan adherence** is `average realised R ÷ average planned R × 100`. Under
100% means you leave the plan early on average; it is not a bug when it is low,
it is the point of the metric.

---

## Outcomes and breakevens

Each closed trade is exactly one of:

| Outcome | Condition |
|---|---|
| **Breakeven** | `|realised R| < breakeven threshold` (default 0.1R). Without a known risk: `|net P&L| < money threshold`. |
| **Win** | Net P&L > 0 |
| **Loss** | Net P&L < 0 |

A breakeven cost you commission, screen time and attention and returned
nothing, so by default it is **excluded** from the win rate and the averages —
it is neither a win nor a loss. It is still counted, still shown, and its total
P&L is on the dashboard, because "9% of my trades were wasted effort" is worth
knowing.

*Settings → Risk* can instead count breakevens as losses or as wins.

---

## Core statistics

| Metric | Formula |
|---|---|
| Win rate | `wins ÷ (wins + losses) × 100` — breakevens excluded by default |
| Gross profit | Sum of net P&L over winners |
| Gross loss | Absolute sum of net P&L over losers |
| Profit factor | `gross profit ÷ gross loss`. Shown as ∞ when there are no losers. |
| Average win / loss | Mean net P&L of winners, of losers |
| Payoff ratio | `average win ÷ |average loss|` |
| Expectancy | `net P&L ÷ number of scored trades` |
| Expectancy in R | Mean realised R across scored trades — the number that compounds |
| Total R | Sum of realised R |
| Largest win / loss | Best and worst single trade |
| Streaks | Longest runs of consecutive wins and losses |

## Drawdown and recovery

The equity curve is `account size + running total of net P&L`, in close-time
order.

```
max drawdown     = max(peak equity − equity) over the period
max drawdown %   = max((peak − equity) ÷ peak) × 100
recovery factor  = net profit ÷ max drawdown
```

The drawdown percentage needs an account size. TradeZulu uses, in order: the
account size in *Settings → Risk*, the account's starting balance, then the
current balance. Set one of them or the percentage is omitted.

## Sharpe and Sortino

Both are annualised from the **daily** P&L series (days with at least one
trade), using the trading days per year from Settings:

```
daily return  = daily P&L ÷ account size
excess        = daily return − (risk-free rate ÷ trading days)

Sharpe  = mean(excess) ÷ stdev(excess) × √(trading days)
Sortino = mean(excess) ÷ downside deviation × √(trading days)
```

Downside deviation counts only the negative excess returns, so upside volatility
does not count against you. Both need at least two trading days, and both are
omitted when the P&L is perfectly flat.

Sharpe is scale-invariant when the risk-free rate is zero, so it is still
meaningful before you have entered an account size.

*Settings → Statistics* can switch the basis to per-trade instead of per-day.

## Kelly

```
Kelly % = (win rate − (1 − win rate) ÷ payoff ratio) × 100
```

The mathematically optimal fraction of the account to risk per trade, given this
win rate and payoff. It assumes your edge is stable and your estimates are
exact, neither of which is true, which is why most people trade a quarter of it.

## Consistency

```
consistency = (1 − largest winning day ÷ total profit from winning days) × 100
```

100% means profit was spread evenly across every green day. 0% means a single
day carried everything, which is the profile that blows up later. With `n`
equally profitable days the score is `(1 − 1/n) × 100`, so it naturally rewards
grinding over lottery tickets.

---

## The Zulu Score

One 0–100 number, in the spirit of TradeZella's Zella Score, built from six
components. Each is scored 0–100 against a target you set, then combined as a
weighted average. Setting a weight to 0 removes a component entirely.

| Component | Score | Default target |
|---|---|---|
| Win rate | `win rate ÷ target × 100`, capped at 100 | 55% |
| Profit factor | `PF ÷ target × 100`, capped | 2.0 |
| Average win/loss | `payoff ÷ target × 100`, capped | 2.0 |
| Max drawdown | `(1 − drawdown% ÷ target) × 100`, floored at 0 — **lower is better** | 20% |
| Recovery factor | `RF ÷ target × 100`, capped | 3.0 |
| Consistency | `consistency ÷ target × 100`, capped | 100% |

A component with no data (a drawdown percentage with no account size, say) is
skipped rather than scored zero, so it cannot silently drag the total down.

Below `min_trades_for_score` trades (default 10) the score is still shown but
flagged as a small sample, because on eight trades it is noise.

Bands: **80+** excellent, **60–79** solid, **40–59** developing, under 40 needs
work.

---

## Reports breakdowns

The same statistics — trades, win rate, profit factor, net P&L and total R —
grouped by symbol, tag, setup, day of week, hour opened, hold time bucket, R
multiple bucket and direction.

The **by tag** view is the one that pays for the journal: it puts a currency
figure on "FOMO trade" and "moved stop". Tag honestly and it will tell you
exactly which habit to kill first.

---

## Excluded trades

Marking a trade *excluded* keeps it in the journal and out of every statistic —
for a fat-finger, a broker error, or a test trade. The dashboard shows how many
are excluded so the exclusion never becomes invisible.
