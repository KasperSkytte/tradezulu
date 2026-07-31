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
    'A floor on account equity. Reach it and the copier flattens the account and stops opening, until you deliberately resume.',
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
  'balance ratio':
    "Size copies in proportion to the two accounts' balances. A slave with half the balance takes half the size.",
  'equity ratio': 'The same, measured on equity, so open profit counts towards what the slave risks.',
  'risk percent':
    "Ignore the master's size entirely and risk a fixed share of the slave's equity against the master's stop.",
  'symbol prefix':
    'Some brokers name the same instrument differently — EURUSD, EURUSD.r, FX_EURUSD. This maps between them so a copy lands on the right market.',
  slippage: 'How far the fill may differ from the price asked for before the order is refused.',
  'magic number':
    "A tag stamped on orders the copier places, so they can be told apart from anything you do by hand in the same terminal.",

  // --- the journal -----------------------------------------------------
  breakeven:
    'A trade that closed within a hair of its entry. Counted separately from wins and losses, because calling it a win flatters the win rate for what was really wasted effort.',
  'zulu score':
    'One number from 0 to 100, weighing six things you choose in Settings. It is a way to compare this month with last, not a grade anyone else recognises.',
  'hold time': 'How long a position was open, from first fill to last.',
  'gross profit': 'Profit before commission, swap and fees.',
  'net p&l': 'What actually reached the account: gross profit less commission, swap and fees.',
  swap: 'The financing charged or paid for holding a position overnight.',
  commission: 'What the broker charged to open and close the trade.',
  'initial balance':
    'What the account started with. Used as the base for percentage returns, and inferred from deposits when it is not set.',
}

/** The definition for a label, if there is one. Case and spacing are ignored. */
export function define(label: string): string | undefined {
  return GLOSSARY[label.trim().toLowerCase().replace(/\s+/g, ' ')]
}
