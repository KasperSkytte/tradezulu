/**
 * Picking a broker and one of its trade servers.
 *
 * MetaTrader has thousands of servers and the name has to be exact -- a
 * misremembered "Vantage-Live" against a broker that calls it
 * "VantageMarkets-Live" is a terminal that never logs in and never says why.
 * Choosing the broker first narrows the list to that broker's own.
 *
 * Brokers add servers without telling anybody, so the list is never a dead
 * end: "Not listed" and any broker whose servers are unknown fall back to
 * typing it, which is what MetaTrader itself shows under File → Open an
 * Account.
 *
 * Shared by the master account form and the slave one. They ask for the same
 * two things and there is no reason for one of them to be a pair of text
 * boxes -- which is what the slave form used to be, leaving the fiddliest
 * field in the application typed from memory on the accounts most likely to
 * be added in a hurry.
 */

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import type { BrokerList } from '../lib/types'
import { Field } from './ui'

const OTHER = '__other__'

export function BrokerServerPicker({
  server,
  onChange,
  disabled,
}: {
  server: string
  /** The chosen server, and the broker's own name for the record. */
  onChange: (next: { server: string; broker: string }) => void
  disabled?: boolean
}) {
  const { data } = useQuery({
    queryKey: ['mt5-brokers'],
    queryFn: () => api.get<BrokerList>('/mt5/brokers'),
    staleTime: 60 * 60 * 1000,
  })
  const brokers = useMemo(() => data?.brokers ?? [], [data])

  const [broker, setBroker] = useState('')
  const [touched, setTouched] = useState(false)

  // A stored server names its broker: it is the same string the provisioner
  // matches on, so an account being edited reopens where it was left rather
  // than on "Select your broker…" with its server apparently unset.
  useEffect(() => {
    if (touched || !server || brokers.length === 0) return
    const owner = brokers.find((entry) =>
      entry.servers.some((name) => name.toLowerCase() === server.toLowerCase()),
    )
    setBroker(owner?.key ?? OTHER)
  }, [server, brokers, touched])

  const chosen = brokers.find((entry) => entry.key === broker)
  const servers = chosen?.servers ?? []
  const freeText = broker === OTHER || broker === '' || servers.length === 0

  const label = (key: string) =>
    key === OTHER ? '' : (brokers.find((entry) => entry.key === key)?.label ?? '')

  return (
    <>
      <Field label="Broker">
        <select
          className="tz-input"
          value={broker}
          disabled={disabled}
          onChange={(event) => {
            const next = event.target.value
            setTouched(true)
            setBroker(next)
            // Keep a server that the new broker also has, and keep a typed one
            // when moving to free text. Otherwise the previous broker's server
            // would sit there selected underneath a different broker.
            const list = brokers.find((entry) => entry.key === next)?.servers ?? []
            const kept = list.length === 1 ? list[0] : list.includes(server) ? server : ''
            onChange({ server: next === OTHER ? server : kept, broker: label(next) })
          }}
        >
          <option value="">Select your broker…</option>
          {brokers.map((entry) => (
            <option key={entry.key} value={entry.key}>
              {entry.label}
            </option>
          ))}
          <option value={OTHER}>Not listed — type the server</option>
        </select>
      </Field>

      <Field
        label="Trade server"
        hint={
          freeText
            ? 'Exactly as it appears in MetaTrader under File → Open an Account.'
            : undefined
        }
      >
        {freeText ? (
          <input
            className="tz-input"
            placeholder="YourBroker-Live"
            autoComplete="off"
            disabled={disabled}
            value={server}
            onChange={(event) => {
              setTouched(true)
              onChange({ server: event.target.value, broker: label(broker) })
            }}
          />
        ) : (
          <select
            className="tz-input"
            value={server}
            disabled={disabled}
            onChange={(event) => {
              setTouched(true)
              onChange({ server: event.target.value, broker: label(broker) })
            }}
          >
            <option value="">Select a server…</option>
            {servers.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        )}
      </Field>
    </>
  )
}
