import type { ChatMessage } from '@/lib/chat-messages'

/**
 * Would replacing local messages with a hydrate snapshot drop the answer?
 *
 * Hydration exists to fill in when a live stream payload was empty. It must
 * never REMOVE an answer already on screen.
 *
 * The bug this guards: hydrateFromStoredSession replaced local state with
 * whatever the session store returned and accepted the first fetch that did
 * not throw. The store does not always have the assistant turn yet at that
 * moment, so a streamed reply was painted and then wiped a few hundred
 * milliseconds later — the user saw a response flash and vanish, with no error
 * anywhere. The retry loop never helped, because it only retried on an
 * exception, and "fetched successfully but stale" looked like success.
 */
export function hydrateWouldDropAnswer(
  local: readonly ChatMessage[],
  fetched: readonly ChatMessage[]
): boolean {
  const hasVisibleAssistant = (messages: readonly ChatMessage[]) =>
    messages.some(message => message.role === 'assistant' && !message.hidden)

  return hasVisibleAssistant(local) && !hasVisibleAssistant(fetched)
}
