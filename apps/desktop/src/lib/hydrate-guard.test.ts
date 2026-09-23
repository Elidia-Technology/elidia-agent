import { describe, expect, it } from 'vitest'

import type { ChatMessage } from '@/lib/chat-messages'

import { hydrateWouldDropAnswer } from './hydrate-guard'

/**
 * Regression cover for "the response flashes and then disappears".
 *
 * hydrateFromStoredSession replaced the rendered messages with whatever the
 * session store returned, and accepted the first fetch that did not throw. The
 * store does not always have the assistant turn yet at that moment, so a
 * streamed reply was painted and then wiped a few hundred milliseconds later —
 * no error, just an empty thread. The retry loop never helped because it only
 * retried on an exception; "fetched successfully but stale" looked like success.
 */

const msg = (role: ChatMessage['role'], text: string, hidden = false): ChatMessage =>
  ({ id: `${role}-${text}`, role, parts: [{ type: 'text', text }], hidden }) as ChatMessage

describe('hydrateWouldDropAnswer', () => {
  it('blocks a stale snapshot that lost the assistant turn', () => {
    const local = [msg('user', 'hi'), msg('assistant', 'the answer')]
    const fetched = [msg('user', 'hi')]

    expect(hydrateWouldDropAnswer(local, fetched)).toBe(true)
  })

  it('allows a snapshot that still carries the assistant turn', () => {
    const local = [msg('user', 'hi'), msg('assistant', 'the answer')]
    const fetched = [msg('user', 'hi'), msg('assistant', 'the answer')]

    expect(hydrateWouldDropAnswer(local, fetched)).toBe(false)
  })

  it('allows hydration when nothing is rendered yet — its actual purpose', () => {
    const local = [msg('user', 'hi')]
    const fetched = [msg('user', 'hi'), msg('assistant', 'recovered from store')]

    expect(hydrateWouldDropAnswer(local, fetched)).toBe(false)
  })

  it('allows an empty-to-empty hydrate', () => {
    expect(hydrateWouldDropAnswer([], [])).toBe(false)
  })

  it('ignores hidden assistant messages on both sides', () => {
    // A hidden assistant message is not something the user can see, so it
    // neither counts as an answer worth protecting nor as one worth restoring.
    const local = [msg('user', 'hi'), msg('assistant', 'internal', true)]
    const fetched = [msg('user', 'hi')]

    expect(hydrateWouldDropAnswer(local, fetched)).toBe(false)
  })

  it('protects a visible answer even when the snapshot has a hidden one', () => {
    const local = [msg('assistant', 'visible answer')]
    const fetched = [msg('assistant', 'hidden only', true)]

    expect(hydrateWouldDropAnswer(local, fetched)).toBe(true)
  })
})
