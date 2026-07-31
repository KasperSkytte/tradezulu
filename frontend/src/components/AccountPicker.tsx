/** Which account every page is looking at.
 *
 *  Sits beside the date range because it is the same kind of control: not a
 *  filter narrowing a list, but the scope the figures are about. Hidden
 *  entirely when there is only one account, since a choice of one is noise.
 */

import { useFilters } from '../lib/filters'

export function AccountPicker() {
  const { filters, accounts, setAccount } = useFilters()

  if (accounts.length < 2) return null

  // Master first: it is the account being traded, and the one whose figures
  // people come to look at. The rest follow in the order they were added.
  const ordered = [...accounts].sort(
    (a, b) => Number(b.role === 'master') - Number(a.role === 'master'),
  )

  return (
    <label className="flex items-center">
      <span className="sr-only">Account</span>
      <select
        className="tz-input h-8 max-w-[11rem] truncate py-0 pr-7 text-sm"
        value={filters.accountId === undefined ? '' : String(filters.accountId)}
        onChange={(event) =>
          setAccount(event.target.value === 'all' ? 'all' : Number(event.target.value))
        }
      >
        {ordered.map((account) => (
          <option key={account.id} value={account.id}>
            {account.name || account.login}
            {account.role === 'master' ? ' · master' : ''}
            {/* No terminal runs for an archived account -- it is a journal you
                can still read, not an account being traded. */}
            {account.role === 'archived' ? ' · archived' : ''}
          </option>
        ))}
        {/* Kept, but it is the last option rather than the default: the
            per-account figures are withheld while it is selected, so it
            answers "what did everything make" and nothing finer. */}
        <option value="all">All accounts</option>
      </select>
    </label>
  )
}
