/**
 * Client for the Elidia gateway's API server.
 *
 * A phone cannot spawn a local agent — Android and iOS do not allow launching a
 * Python CLI — so unlike the desktop (`elidia dashboard`) and the VS Code
 * extension (`elidia-acp`), mobile talks to a REMOTE agent over HTTPS.
 *
 * That agent is the user's own gateway running with the api_server platform
 * enabled. Endpoints and behaviour below were verified against a running
 * instance, not read from documentation:
 *
 *   GET  /v1/capabilities   200 with Bearer, 401 without
 *   GET  /v1/models         200 with Bearer, 401 without
 *   GET  /api/sessions      200 with Bearer, 401 without
 *   POST /api/sessions      201
 */

export interface GatewayConfig {
  baseUrl: string
  apiKey: string
}

export interface Session {
  id: string
  title?: string
  updated_at?: string
  message_count?: number
}

export interface Message {
  role: string
  content: string
}

export class GatewayError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

/** Strip a trailing slash so path joining cannot produce a double slash. */
export function normalizeBaseUrl(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, '')
  if (!trimmed) throw new Error('Enter your gateway address.')
  if (!/^https?:\/\//i.test(trimmed)) {
    // Default to https: a phone on a public network sending a bearer token over
    // http would leak it to anyone on the path.
    return `https://${trimmed}`
  }
  return trimmed
}

export class Gateway {
  private readonly baseUrl: string
  private readonly apiKey: string

  constructor(config: GatewayConfig) {
    this.baseUrl = normalizeBaseUrl(config.baseUrl)
    this.apiKey = config.apiKey.trim()
  }

  private headers(json = false): Record<string, string> {
    const h: Record<string, string> = { Authorization: `Bearer ${this.apiKey}` }
    if (json) h['Content-Type'] = 'application/json'
    return h
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    let response: Response
    try {
      response = await fetch(`${this.baseUrl}${path}`, {
        method,
        headers: this.headers(body !== undefined),
        body: body === undefined ? undefined : JSON.stringify(body),
      })
    } catch (cause) {
      // fetch rejects for DNS, TLS and connection failures. On a phone this is
      // the common case — wrong address, gateway not running, or not reachable
      // from this network — so it must not surface as a bare "Failed to fetch".
      throw new GatewayError(
        `Cannot reach ${this.baseUrl}. Check the address, and that the gateway is running and reachable from this device.`,
        0
      )
    }

    if (response.status === 401) {
      throw new GatewayError('The gateway rejected this API key.', 401)
    }
    if (!response.ok) {
      const detail = (await response.text().catch(() => '')).slice(0, 300)
      throw new GatewayError(`${response.status} from ${path}${detail ? `: ${detail}` : ''}`, response.status)
    }
    if (response.status === 204) return undefined as T
    const text = await response.text()
    if (!text) return undefined as T
    try {
      return JSON.parse(text) as T
    } catch {
      return text as unknown as T
    }
  }

  /**
   * Confirm the address and key before storing them.
   *
   * /v1/capabilities is the endpoint the server itself describes as
   * "machine-readable API capabilities for external UIs", and it is gated, so a
   * 200 proves both that the gateway is there and that the key works.
   */
  async verify(): Promise<Record<string, unknown>> {
    return this.request<Record<string, unknown>>('GET', '/v1/capabilities')
  }

  async listSessions(): Promise<Session[]> {
    const data = await this.request<any>('GET', '/api/sessions')
    if (Array.isArray(data)) return data
    if (Array.isArray(data?.sessions)) return data.sessions
    return []
  }

  async createSession(): Promise<string> {
    const data = await this.request<any>('POST', '/api/sessions', {})
    const id = data?.id ?? data?.session_id
    if (!id) throw new GatewayError('The gateway did not return a session id.', 0)
    return String(id)
  }

  async messages(sessionId: string): Promise<Message[]> {
    const data = await this.request<any>('GET', `/api/sessions/${sessionId}/messages`)
    const raw = Array.isArray(data) ? data : (data?.messages ?? [])
    return raw
      .filter((m: any) => m && (m.role === 'user' || m.role === 'assistant'))
      .map((m: any) => ({
        role: String(m.role),
        content: typeof m.content === 'string' ? m.content : JSON.stringify(m.content),
      }))
  }

  async deleteSession(sessionId: string): Promise<void> {
    await this.request('DELETE', `/api/sessions/${sessionId}`)
  }

  /**
   * Send a message and stream the reply.
   *
   * `onChunk` is called with each text fragment as it arrives. The server sends
   * server-sent events; a chunk boundary can split a line, so the buffer is
   * carried between reads rather than parsed per-read.
   */
  async chatStream(
    sessionId: string,
    content: string,
    onChunk: (text: string) => void,
    signal?: AbortSignal
  ): Promise<void> {
    const response = await fetch(`${this.baseUrl}/api/sessions/${sessionId}/chat/stream`, {
      method: 'POST',
      headers: this.headers(true),
      body: JSON.stringify({ content }),
      signal,
    }).catch(() => {
      throw new GatewayError(`Cannot reach ${this.baseUrl}.`, 0)
    })

    if (response.status === 401) throw new GatewayError('The gateway rejected this API key.', 401)
    if (!response.ok) {
      const detail = (await response.text().catch(() => '')).slice(0, 300)
      throw new GatewayError(`${response.status} while streaming${detail ? `: ${detail}` : ''}`, response.status)
    }
    if (!response.body) throw new GatewayError('The gateway returned no response body.', 0)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      let newline: number
      while ((newline = buffer.indexOf('\n')) >= 0) {
        const line = buffer.slice(0, newline).trim()
        buffer = buffer.slice(newline + 1)
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (!payload || payload === '[DONE]') continue
        try {
          const event = JSON.parse(payload)
          const text =
            event?.delta ??
            event?.content ??
            event?.choices?.[0]?.delta?.content ??
            ''
          if (text) onChunk(String(text))
        } catch {
          // A non-JSON data line is informational, not a protocol break.
        }
      }
    }
  }
}
