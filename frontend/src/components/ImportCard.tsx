/** Reading history out of a file instead of off a terminal.
 *
 *  This lived under Settings → Data, which is where you put a thing when you
 *  cannot think where else it goes. It belongs with the accounts: it is the
 *  other way an account's trades get into TradeZulu, and the connection card
 *  above offers "Manual import" as an alternative to running a terminal at
 *  all — with nothing on that page to actually import with.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { Upload } from 'lucide-react'
import { api, ApiError } from '../lib/api'
import { Button, Card, CardHeader } from './ui'

export function ImportCard() {
  const queryClient = useQueryClient()
  const fileInput = useRef<HTMLInputElement>(null)
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.upload<{ created: number; updated: number; kind: string }>('/import/file', form)
    },
    onSuccess: (imported) => {
      setError(null)
      setResult(
        `Imported ${imported.created} new and updated ${imported.updated} existing trades ` +
          `from the ${imported.kind === 'mt5_html' ? 'MetaTrader report' : 'CSV'}.`,
      )
      void queryClient.invalidateQueries()
    },
    onError: (caught) => {
      setResult(null)
      setError(caught instanceof ApiError ? caught.message : 'Import failed')
    },
  })

  return (
    <Card>
      <CardHeader
        title="Manual import"
        hint="For history no terminal was running for, or if you would rather not run one at all."
      />
      <p className="mb-3 text-sm text-[var(--tz-text-muted)]">
        In MetaTrader 5: <strong>Toolbox → History</strong>, right-click → <strong>Report</strong>,
        and save as HTML or XLSX — either works. Plain CSV exports are read too, as long as they
        have symbol, open time and price columns. The account number in the file decides which
        account the trades land under; deals are matched on their ticket, so importing the same
        statement twice changes nothing.
      </p>
      <input
        ref={fileInput}
        type="file"
        accept=".html,.htm,.xlsx,.xlsm,.csv,.txt"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) upload.mutate(file)
          event.target.value = ''
        }}
      />
      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          icon={<Upload size={15} />}
          loading={upload.isPending}
          onClick={() => fileInput.current?.click()}
        >
          Choose a file
        </Button>
      </div>
      {result && <p className="mt-3 text-sm text-[var(--tz-gain-text)]">{result}</p>}
      {error && <p className="mt-3 text-sm text-[var(--tz-loss-text)]">{error}</p>}
    </Card>
  )
}
