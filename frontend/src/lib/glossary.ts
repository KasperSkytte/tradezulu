/**
 * Plain-English definitions for the terms this app uses.
 *
 * Trading writing is full of words that sound like everyone already knows
 * them — Kelly fraction, expectancy, R multiple. Somebody meeting one for the
 * first time should not have to leave the page to find out what it means, so
 * every term the interface shows has an entry here and an info icon beside it.
 *
 * Keys are matched case-insensitively against the label, so a component only
 * has to render its label to get the explanation.
 */

export const GLOSSARY: Record<string, string> = {
  // --- the core numbers ------------------------------------------------
  'win rate':
    'Winners divided by winners plus losers. Breakevens are left out by default, since a trade that ended where it started was neither.',
  'profit factor':
    'Gross profit divided by gross loss. Above 1 means the winners paid for the losers; 2 means they paid twice over.',
  expectancy:
    'What one average trade is worth, in R. Multiply by how many trades you take to see what the edge is worth over time. Negative means the strategy loses money however good it feels.',
  'r multiple':
    'Profit measured in units of what the trade risked. Risk £100 and make £250 and that is +2.5R. It lets trades of different sizes be compared honestly.',
  'planned r':
    'What the trade would have made in R if it had reached its target, measured from the stop you set when you opened it.',
  'realised r': 'What the trade actually made, in units of what it risked.',
  'average win': 'The mean profit of the trades that made money.',
  'average loss': 'The mean loss of the trades that lost money.',
  'payoff ratio':
    'Average win divided by average loss. Below 1 means you need to win often; above 2 means you can be wrong most of the time and still make money.',

  // --- risk ------------------------------------------------------------
  'kelly fraction':
    'The share of your account that maximises long-run growth, given your win rate and payoff ratio. Mainly a sanity check: full Kelly is famously wild, and most people trade a quarter of it or less. If this reads high, the sample is probably too small to trust.',
  'max drawdown':
    'The deepest fall from a peak in the equity curve, as a percentage. It is the worst stretch you actually lived through, and the number that decides whether a strategy is survivable.',
  'recovery factor':
    'Net profit divided by the largest drawdown. How much you made for the worst pain you took along the way.',
  'risk of ruin':
    'The chance of losing enough of the account to be unable to continue, given the current win rate and risk per trade.',
  'sharpe ratio':
    'Return divided by how much the returns bounce around. Higher means smoother; it says nothing about whether the returns are large.',
  'equity stop':
    'A floor on account equity. Reaching it halts the account until you deliberately resume; whether the open copies are closed as well is the "When one of those trips" setting beside it.',
  'daily drawdown':
    'How far the account may fall from where it opened today before copying stops for the day.',
  consistency:
    'How evenly profit is spread across days. Prop firms often require that no single day is more than a set share of total profit, and one enormous day can fail an otherwise good account.',

  // --- copier ----------------------------------------------------------
  'master account':
    'The account whose trades are copied. TradeZulu only ever reads it, so an investor password is enough.',
  'slave account':
    'An account that receives copies. This one needs a real password, which is why it stays in dry-run until you arm it.',
  'dry run':
    'The copier works out exactly what it would do and records it, without sending a single order. The safe way to watch a new account for a day.',
  'sizing mode':
    'How a copy is sized against the master: a fixed lot, a multiplier, in proportion to balance or equity, or by risking a fixed percentage against the master stop.',
  'position sizing':
    'How big each copied trade should be. Everything else on the form limits or refuses a trade; this decides the number of lots in the first place.',
  'largest position (lots)':
    'A ceiling on any single copy, whatever the sizing worked out. What happens at that size is the next setting: trade it smaller, or skip it. 0 means no ceiling.',
  'at that size':
    'Whether reaching the ceiling shrinks the trade to it or refuses the trade outright. Shrinking keeps you in the move at a size you chose; skipping keeps the copy a faithful one or nothing at all.',
  'smallest position (lots)':
    "The smallest order to send. Sizing always rounds down, so a slave a fraction smaller than the master can compute 0.00998 lots and refuse the trade outright; setting a minimum lets it round up to this instead. 0 uses the broker's own minimum and refuses anything under it.",
  'require a stop loss':
    'Refuse to copy a master trade that has no stop attached, rather than opening an unprotected position on the slave. The two risk-percentage modes always do this, whatever the switch says: a percentage of an account is not a size until there is a stop to measure it against.',
  // --- the copier's limits, in the order the form asks them ------------
  'risk per trade (%)':
    "The share of the slave's own account to put at stake on each copy, measured against the master's stop distance. The master's size is ignored entirely.",
  'risk over (% equity)':
    'Refuse a copy that would risk more than this share of the slave equity. A ceiling on top of whatever the sizing worked out, and it also refuses when the broker has not said what a lot of the instrument is worth -- the one case where sizing is least trustworthy.',
  'stop closer than (points)':
    'Refuse a copy whose stop is nearer the entry than this. Points, not pips: one unit of the last digit the broker quotes, so it means the same on a 5-digit currency as on a 2-digit metal. A stop this tight does not survive two brokers quoting slightly different prices -- the slave fills a little worse, and the loss is wider by the same proportion.',
  'open positions':
    'Refuse a new copy once this many are already open on the slave, whatever they are.',
  'same direction':
    'Refuse a new copy once this many open positions already face the same way, across all instruments. A hedge book that is really one big bet is what this catches.',
  'per symbol': 'Refuse a new copy once this many are already open in that one instrument.',
  'total lots': 'Refuse a copy that would take the total volume open on the slave past this.',
  'no new trades when down (%)':
    'Stop opening copies while the account is this far under water, and start again by itself once it recovers. Unlike the limits below it this does not latch: it is a pause for a bad morning, not a stop that has to be cleared.',
  'measured from':
    'What that drawdown is counted from: the highest equity the account has reached, or the equity it opened today with. "How far off my best" and "how bad is today" are different questions.',
  'down today (%)':
    "Halt the account after losing this share of the day's opening equity. A halt stays until you resume it by hand.",
  'below peak (%)':
    'Halt the account once equity falls this far below its high-water mark. A halt stays until you resume it by hand.',
  'up today (%)':
    "Stop opening once the day's profit reaches this share of the opening equity -- for prop rules that punish a single outsized day, and for anyone who knows what they do after a good morning.",
  'one day max (% of profit)':
    'Block new copies once today would account for more than this share of total profit. Prop consistency rules fail an account on exactly this, and one enormous day is what usually does it.',
  'bank a winner at':
    'Close a copied position once it is this far in profit, in account currency. A way to cap the outsized win that trips a consistency rule.',
  '…or at (r)':
    'The same, in multiples of what that trade was risking -- so it scales with the trade rather than with the account.',
  'when one of those trips':
    'What a halt does to positions already open: close them all, or leave them to be managed while nothing new is opened. The third choice flattens only on the equity stop and merely stops opening for the softer limits.',
  "follow the master's stop and target changes":
    'Mirror a stop or target the master moves onto the copy. Off, the copy keeps whatever it opened with.',
  'only these':
    'Copy nothing but these instruments. Leave it empty to copy everything the master trades.',
  'never these': 'Never copy these instruments. Checked after the allowed list.',
  'equity falls to':
    'An amount in account currency, not a loss. The account stops when equity reaches this number.',
  'balance ratio':
    "Size copies in proportion to the two accounts' balances. A slave with half the balance takes half the size.",
  'equity ratio': 'The same, measured on equity, so open profit counts towards what the slave risks.',
  'risk percent':
    "Ignore the master's size entirely and risk a fixed share of the slave's equity against the master's stop. A master trade with no stop is refused rather than sized some other way -- asking for 1% and getting a balance-scaled lot instead is a different trade under the name of the one you configured.",
  'symbol prefix':
    'Some brokers name the same instrument differently — EURUSD, EURUSD.r, FX_EURUSD. This maps between them so a copy lands on the right market.',
  slippage: 'How far the fill may differ from the price asked for before the order is refused.',
  'magic number':
    "A tag stamped on orders the copier places, so they can be told apart from anything you do by hand in the same terminal.",

  // --- the journal -----------------------------------------------------
  breakeven:
    'A trade that closed within a hair of its entry. Counted separately from wins and losses, because calling it a win flatters the win rate for what was really wasted effort.',
  'zulu score':
    'One number from 0 to 100, built from the seven components you weight in Settings — six of them are on out of the box. It is a way to compare this month with last, not a grade anyone else recognises.',
  'hold time': 'How long a position was open, from first fill to last.',
  'net roi':
    "The trade as a share of what the account was worth when it was opened. Shown beside the money because the same $700 means one thing on a $5,000 account and another on a $50,000 one -- and with amounts hidden the P&L column already says this, so the column steps aside.",
  'risk taken':
    'What this trade put at stake, from its stop, against the equity the account held when it opened.',
  'gross profit': 'Profit before commission, swap and fees.',
  gross: 'Profit before commission, swap and fees.',
  net: 'What actually reached the account: gross profit less commission, swap and fees.',
  entry: 'The price this position was opened at, averaged over its opening fills.',
  exit: 'The price it was closed at, averaged over its closing fills.',
  volume: 'The size of the position, in lots.',
  'stop distance': 'How far the stop sat from the entry, in the price units the broker quotes.',
  'initial stop':
    'The stop this trade started with. Everything in R is measured from it, so correcting it here recalculates the R figures for this trade.',
  'initial target': 'The target this trade started with. Planned R is measured to it.',
  'net p&l': 'What actually reached the account: gross profit less commission, swap and fees.',
  swap: 'The financing charged or paid for holding a position overnight.',
  commission: 'What the broker charged to open and close the trade.',
  'initial balance':
    'What the account started with, inferred from your deposits when it is not set. Drawdown, Sharpe and the equity curve are measured from it. Per-trade risk is not: that is measured against the equity at the moment each trade was opened, which is what it actually put at stake.',
}

/** The definition for a label, if there is one. Case and spacing are ignored. */
export function define(label: string): string | undefined {
  return GLOSSARY[label.trim().toLowerCase().replace(/\s+/g, ' ')]
}
