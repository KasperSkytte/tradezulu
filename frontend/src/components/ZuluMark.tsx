/** The TradeZulu mark: a rising Z drawn as a candle-chart staircase. */
export function ZuluMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} role="img" aria-label="TradeZulu">
      <defs>
        <linearGradient id="tz-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#2fd8a0" />
          <stop offset="100%" stopColor="#087a58" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="8" fill="url(#tz-mark)" />
      <path
        d="M9 10h14l-9.5 12H23"
        fill="none"
        stroke="white"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="23" cy="22" r="2.6" fill="#ecfdf5" />
    </svg>
  )
}
