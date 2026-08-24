import { useEffect, useState } from 'react'

import { Gateway, GatewayError, Session } from '../lib/gateway'

/** The same sessions the desktop and CLI see — this is one agent, not a copy. */
export function Sessions({
  gateway,
  onOpen,
  onUnpair,
}: {
  gateway: Gateway
  onOpen: (id: string) => void
  onUnpair: () => void
}) {
  const [sessions, setSessions] = useState<Session[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      setSessions(await gateway.listSessions())
    } catch (err) {
      setError(err instanceof GatewayError ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gateway])

  async function startNew() {
    setError(null)
    try {
      onOpen(await gateway.createSession())
    } catch (err) {
      setError(err instanceof GatewayError ? err.message : String(err))
    }
  }

  return (
    <div className="sessions">
      <header>
        <span className="title">Elidia</span>
        <button className="link" onClick={onUnpair}>Disconnect</button>
      </header>

      <button className="primary" onClick={startNew}>New conversation</button>

      {loading && <p className="muted center">Loading…</p>}
      {error && <p className="error">{error}</p>}
      {!loading && !error && sessions.length === 0 && (
        <p className="muted center">No conversations yet.</p>
      )}

      <ul>
        {sessions.map(s => (
          <li key={s.id}>
            <button onClick={() => onOpen(s.id)}>
              <span className="name">{s.title || s.id.slice(0, 8)}</span>
              {s.updated_at && <span className="when">{s.updated_at.slice(0, 16).replace('T', ' ')}</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
