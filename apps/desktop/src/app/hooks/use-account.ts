import { useEffect, useState } from 'react'

/**
 * The signed-in AiUtils user, for surfaces that can draw one.
 *
 * The renderer cannot call the Developer API directly: the API key lives in the
 * CLI process and deliberately never travels into the browser context. The CLI
 * exposes /api/account, and this reads it once per mount.
 *
 * Running Elidia with no AiUtils account is supported, so "not configured" is a
 * normal state rather than an error — every consumer must render something
 * sensible when this returns null.
 */

export type Account = {
  id?: string | null
  full_name?: string | null
  email?: string | null
  avatar_url?: string | null
}

type AccountResponse = Account & {
  configured?: boolean
  available?: boolean
  reason?: string
}

export function useAccount(): { account: Account | null; loading: boolean } {
  const [account, setAccount] = useState<Account | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false

    void (async () => {
      try {
        const result = await window.elidiaDesktop.api<AccountResponse>({ path: '/api/account' })

        if (cancelled) {
          return
        }

        // configured=false means no AiUtils key, available=false means the
        // gateway could not be reached just now. Both mean "draw the fallback",
        // and neither is worth surfacing as an error in a chat window.
        setAccount(result?.configured && result?.available ? result : null)
      } catch {
        if (!cancelled) {
          setAccount(null)
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    })()

    return () => {
      cancelled = true
    }
  }, [])

  return { account, loading }
}

/**
 * Initials for an account, or null when there is nothing honest to derive.
 *
 * Falls back from name to the local part of an email, because "ada.lovelace@…"
 * still tells you who this is. Returns null rather than inventing a letter when
 * neither exists — an avatar reading "A" for an account with no name is a
 * fabrication, and a plain glyph is the truthful answer.
 */
export function initialsFor(account: Account | null): string | null {
  const source = (account?.full_name || '').trim() || (account?.email || '').split('@')[0]?.trim()

  if (!source) {
    return null
  }

  const words = source.split(/[\s._-]+/).filter(Boolean)

  if (words.length === 0) {
    return null
  }

  const letters = words.length === 1 ? words[0].slice(0, 2) : `${words[0][0]}${words[words.length - 1][0]}`

  return letters.toUpperCase() || null
}
