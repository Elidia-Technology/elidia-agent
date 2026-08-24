import { useState } from 'react'

import { Gateway, GatewayError, normalizeBaseUrl } from '../lib/gateway'
import { savePairing } from '../lib/credentials'

/**
 * First run: point the app at the user's own gateway.
 *
 * The address is verified against /v1/capabilities BEFORE anything is stored,
 * so a typo or a wrong key fails here with a specific message rather than
 * later, mid-conversation, as an opaque error.
 */
export function Pair({ onPaired }: { onPaired: (g: Gateway) => void }) {
  const [address, setAddress] = useState('')
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function connect(event: React.FormEvent) {
    event.preventDefault()
    setError(null)

    let baseUrl: string
    try {
      baseUrl = normalizeBaseUrl(address)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      return
    }
    if (!key.trim()) {
      setError('Enter the API key your gateway is configured with.')
      return
    }

    setBusy(true)
    try {
      const gateway = new Gateway({ baseUrl, apiKey: key })
      await gateway.verify()
      await savePairing({ baseUrl, apiKey: key.trim() })
      onPaired(gateway)
    } catch (err) {
      setError(
        err instanceof GatewayError
          ? err.message
          : `Could not connect: ${err instanceof Error ? err.message : String(err)}`
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="pair" onSubmit={connect}>
      <h1>Connect to your agent</h1>
      <p className="muted">
        Elidia runs on your own machine. Enter the address of your gateway and
        the API key it is configured with.
      </p>

      <label>
        Gateway address
        <input
          value={address}
          onChange={e => setAddress(e.target.value)}
          placeholder="elidia.example.com"
          autoCapitalize="none"
          autoCorrect="off"
          inputMode="url"
          disabled={busy}
        />
      </label>

      <label>
        API key
        <input
          value={key}
          onChange={e => setKey(e.target.value)}
          placeholder="your API_SERVER_KEY"
          type="password"
          autoCapitalize="none"
          autoCorrect="off"
          disabled={busy}
        />
      </label>

      {error && <p className="error">{error}</p>}

      <button type="submit" disabled={busy}>
        {busy ? 'Checking…' : 'Connect'}
      </button>

      <p className="hint">
        Start the gateway with <code>API_SERVER_ENABLED=true</code> and
        <code> API_SERVER_KEY=…</code>. The key is stored on this device only.
      </p>
    </form>
  )
}
