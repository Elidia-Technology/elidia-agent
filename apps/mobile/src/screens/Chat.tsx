import { useEffect, useRef, useState } from 'react'

import { Gateway, GatewayError, Message } from '../lib/gateway'

/**
 * The conversation.
 *
 * Replies stream, so the assistant turn is appended into as chunks arrive
 * rather than appearing all at once — on a phone, a long wait with no output
 * reads as a hang.
 */
export function Chat({
  gateway,
  sessionId,
  onBack,
}: {
  gateway: Gateway
  sessionId: string
  onBack: () => void
}) {
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const abort = useRef<AbortController | null>(null)
  const log = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let cancelled = false
    gateway
      .messages(sessionId)
      .then(m => {
        if (!cancelled) setMessages(m)
      })
      .catch(err => {
        if (!cancelled) setError(err instanceof GatewayError ? err.message : String(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
      // Leaving the screen mid-turn must not leave a stream running.
      abort.current?.abort()
    }
  }, [gateway, sessionId])

  useEffect(() => {
    log.current?.scrollTo({ top: log.current.scrollHeight })
  }, [messages])

  async function send(event: React.FormEvent) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || busy) return

    setError(null)
    setDraft('')
    setMessages(prev => [...prev, { role: 'user', content: text }, { role: 'assistant', content: '' }])
    setBusy(true)

    const controller = new AbortController()
    abort.current = controller

    try {
      await gateway.chatStream(
        sessionId,
        text,
        chunk =>
          setMessages(prev => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last?.role === 'assistant') {
              next[next.length - 1] = { ...last, content: last.content + chunk }
            }
            return next
          }),
        controller.signal
      )
    } catch (err) {
      if (controller.signal.aborted) {
        setMessages(prev => {
          const next = [...prev]
          const last = next[next.length - 1]
          if (last?.role === 'assistant' && !last.content) {
            // Drop an empty turn rather than leaving a blank bubble behind.
            next.pop()
          }
          return next
        })
      } else {
        setError(err instanceof GatewayError ? err.message : String(err))
      }
    } finally {
      setBusy(false)
      abort.current = null
    }
  }

  return (
    <div className="chat">
      <header>
        <button className="back" onClick={onBack} aria-label="Back to sessions">‹</button>
        <span className="title">Elidia</span>
        {busy && (
          <button className="stop" onClick={() => abort.current?.abort()}>
            Stop
          </button>
        )}
      </header>

      <div className="log" ref={log}>
        {loading && <p className="muted center">Loading…</p>}
        {!loading && messages.length === 0 && (
          <p className="muted center">Ask Elidia something about your workspace.</p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`turn ${m.role}`}>
            <div className="role">{m.role === 'user' ? 'you' : 'elidia'}</div>
            <div className="body">
              {m.content || (busy && i === messages.length - 1 ? '…' : '')}
            </div>
          </div>
        ))}
        {error && <p className="error">{error}</p>}
      </div>

      <form className="composer" onSubmit={send}>
        <textarea
          value={draft}
          onChange={e => setDraft(e.target.value)}
          placeholder="Message Elidia…"
          rows={1}
          disabled={busy}
        />
        <button type="submit" disabled={busy || !draft.trim()}>
          Send
        </button>
      </form>
    </div>
  )
}
