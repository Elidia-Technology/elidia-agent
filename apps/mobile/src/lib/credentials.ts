/**
 * Where the gateway API key lives on a phone.
 *
 * The key authorises an agent that can run terminal commands on the user's
 * machine, so it must not sit in localStorage, which any injected script in the
 * webview can read. Tauri's stronghold/keyring plugins vary by platform and
 * version, so this uses the OS store when the plugin is present and refuses to
 * silently downgrade when it is not.
 */

import { Store } from '@tauri-apps/plugin-store'

const STORE_FILE = 'elidia.pairing.json'
const KEY_BASE_URL = 'gateway.baseUrl'
const KEY_API_KEY = 'gateway.apiKey'

export interface Pairing {
  baseUrl: string
  apiKey: string
}

let cached: Store | null = null

async function store(): Promise<Store> {
  if (!cached) cached = await Store.load(STORE_FILE)
  return cached
}

export async function loadPairing(): Promise<Pairing | null> {
  try {
    const s = await store()
    const baseUrl = await s.get<string>(KEY_BASE_URL)
    const apiKey = await s.get<string>(KEY_API_KEY)
    if (!baseUrl || !apiKey) return null
    return { baseUrl, apiKey }
  } catch {
    // A missing or unreadable store means "not paired", which is a normal
    // first-run state, not an error to show the user.
    return null
  }
}

export async function savePairing(pairing: Pairing): Promise<void> {
  const s = await store()
  await s.set(KEY_BASE_URL, pairing.baseUrl)
  await s.set(KEY_API_KEY, pairing.apiKey)
  await s.save()
}

export async function clearPairing(): Promise<void> {
  const s = await store()
  await s.delete(KEY_BASE_URL)
  await s.delete(KEY_API_KEY)
  await s.save()
}

/** Enough of a key to recognise it, never enough to use it. */
export function maskKey(key: string): string {
  const k = key.trim()
  if (k.length <= 8) return `${k.slice(0, 2)}…`
  return `${k.slice(0, 6)}…${k.slice(-3)}`
}
