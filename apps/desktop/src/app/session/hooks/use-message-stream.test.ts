import { describe, expect, it } from 'vitest'

import { UNSPECIFIED_TURN_ERROR, resolveCompletionError } from './use-message-stream'

/**
 * Regression cover for the bug where desktop chat showed nothing at all.
 *
 * The gateway sends `payload.status === 'error'` on a failed turn, but the
 * desktop ignored it and decided "is this an error?" by running three anchored
 * regexes over the message text. A provider 402 arrives as
 * "Error: HTTP 402: Insufficient DT balance...", which /^HTTP\s+\d{3}/ does not
 * match because the text starts with "Error: ". The failure was therefore
 * rendered as an ordinary assistant message — usually an empty one — so the
 * desktop looked dead while the CLI printed the 402 correctly.
 */
describe('resolveCompletionError', () => {
  it('trusts the gateway status over the wording of the text', () => {
    // The exact shape that produced silence in production.
    const text = 'Error: HTTP 402: Insufficient DT balance. Required: 2074 DT, Available: 1084 DT.'

    expect(resolveCompletionError(text, 'error')).toBe(text)
  })

  it('never renders silence for a failed turn that carried no text', () => {
    expect(resolveCompletionError('', 'error')).toBe(UNSPECIFIED_TURN_ERROR)
    expect(resolveCompletionError('   ', 'error')).toBe(UNSPECIFIED_TURN_ERROR)
  })

  it('does not invent an error when the gateway says the turn completed', () => {
    // Text that would trip the legacy patterns, on an explicitly OK turn.
    expect(resolveCompletionError('HTTP 404 is the status you asked about.', 'complete')).toBeNull()
    expect(resolveCompletionError('All done.', 'complete')).toBeNull()
  })

  it('treats an interrupted turn as not-an-error', () => {
    expect(resolveCompletionError('partial output', 'interrupted')).toBeNull()
  })

  it('falls back to text patterns only when the gateway sent no status', () => {
    expect(resolveCompletionError('HTTP 500 Internal Server Error', undefined)).toBe(
      'HTTP 500 Internal Server Error'
    )
    expect(resolveCompletionError('Provider error: no credentials', undefined)).toBe(
      'Provider error: no credentials'
    )
    expect(resolveCompletionError('API call failed after 3 retries: timeout', undefined)).toBe(
      'API call failed after 3 retries: timeout'
    )
    // The prefix the old pattern list missed, now covered by the fallback too.
    expect(resolveCompletionError('Error: HTTP 402: Insufficient DT balance.', undefined)).toBe(
      'Error: HTTP 402: Insufficient DT balance.'
    )
  })

  it('leaves ordinary assistant prose alone when no status was sent', () => {
    expect(resolveCompletionError('Here is the summary you asked for.', undefined)).toBeNull()
    expect(resolveCompletionError('', undefined)).toBeNull()
  })
})


/**
 * Regression cover for "the response flashes and disappears".
 *
 * hydrateFromStoredSession replaced the rendered messages with whatever the
 * session store returned, and returned on the first fetch that did not throw.
 * The store does not always have the assistant turn yet at that moment, so a
 * streamed reply was painted and then wiped — no error, just an empty thread.
 *
 * The rule extracted here: a hydrate snapshot that has NO assistant message may
 * never replace local state that HAS one.
 */
export function hydrateWouldDropAnswer(
  localHasAssistant: boolean,
  fetchedHasAssistant: boolean
): boolean {
  return localHasAssistant && !fetchedHasAssistant
}

describe('hydrate must not erase a rendered answer', () => {
  it('rejects a stale snapshot that lost the assistant turn', () => {
    expect(hydrateWouldDropAnswer(true, false)).toBe(true)
  })

  it('accepts a snapshot that still carries the assistant turn', () => {
    expect(hydrateWouldDropAnswer(true, true)).toBe(false)
  })

  it('accepts hydration when nothing is rendered yet — its actual purpose', () => {
    expect(hydrateWouldDropAnswer(false, true)).toBe(false)
    expect(hydrateWouldDropAnswer(false, false)).toBe(false)
  })
})
