/**
 * Reading appearance: font family + text size.
 *
 * Unlike the pairing in `credentials.ts`, none of this is a secret — it is
 * just a display preference, so there is no need for the OS-backed
 * `@tauri-apps/plugin-store`. localStorage is synchronous, so the saved
 * preference can be read and applied to the document before React's first
 * render, avoiding a flash of the default font/size on every launch. The
 * async plugin-store would only be able to apply the preference after a
 * render has already happened.
 */

/** The stack the app has always used, kept as the "System" preset so the
 * default appearance renders pixel-identical to before this feature. */
const SYSTEM_FONT_STACK = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'

export type FontFamilyId = 'system' | 'serif' | 'rounded' | 'monospace'
export type FontSizeId = 'small' | 'default' | 'large' | 'larger' | 'largest'

export interface FontFamilyPreset {
  readonly id: FontFamilyId
  readonly label: string
  /** CSS font-family value. Every stack here resolves on Android and iOS
   * without a network fetch: each ends in a widely-installed face or a
   * generic family, so there is nothing to download and nothing to fail. */
  readonly stack: string
}

export interface FontSizePreset {
  readonly id: FontSizeId
  readonly label: string
  readonly scale: number
}

export interface Appearance {
  readonly familyId: FontFamilyId
  readonly sizeId: FontSizeId
}

export const FAMILY_PRESETS: readonly FontFamilyPreset[] = [
  { id: 'system', label: 'System', stack: SYSTEM_FONT_STACK },
  { id: 'serif', label: 'Serif', stack: `Georgia, "Times New Roman", Times, serif` },
  {
    id: 'rounded',
    label: 'Rounded',
    // Humanist/rounded faces bundled with the OS; falls back to the same
    // system stack as the "System" preset when neither is installed.
    stack: `"Avenir Next", Avenir, "Segoe UI Rounded", ${SYSTEM_FONT_STACK}`,
  },
  {
    id: 'monospace',
    label: 'Monospace',
    stack: `"SF Mono", Menlo, "Cascadia Code", Consolas, "Roboto Mono", monospace`,
  },
]

export const SIZE_PRESETS: readonly FontSizePreset[] = [
  { id: 'small', label: 'Small', scale: 0.9 },
  { id: 'default', label: 'Default', scale: 1 },
  { id: 'large', label: 'Large', scale: 1.1 },
  { id: 'larger', label: 'Larger', scale: 1.2 },
  { id: 'largest', label: 'Largest', scale: 1.35 },
]

export const DEFAULT_APPEARANCE: Appearance = { familyId: 'system', sizeId: 'default' }

const STORAGE_KEY = 'elidia.appearance'

export function getFamilyPreset(id: FontFamilyId): FontFamilyPreset {
  return FAMILY_PRESETS.find(p => p.id === id) ?? FAMILY_PRESETS[0]
}

export function getSizePreset(id: FontSizeId): FontSizePreset {
  return SIZE_PRESETS.find(p => p.id === id) ?? SIZE_PRESETS[1]
}

function isFamilyId(value: unknown): value is FontFamilyId {
  return typeof value === 'string' && FAMILY_PRESETS.some(p => p.id === value)
}

function isSizeId(value: unknown): value is FontSizeId {
  return typeof value === 'string' && SIZE_PRESETS.some(p => p.id === value)
}

/** Accepts whatever was parsed out of storage — including `null`,
 * mismatched shapes, or values from a future/older version of this app —
 * and returns a value that is always safe to apply. Each field is
 * normalised independently so a corrupt size doesn't also discard a valid
 * family. */
export function normalizeAppearance(value: unknown): Appearance {
  const candidate = value && typeof value === 'object' ? (value as Record<string, unknown>) : {}
  return {
    familyId: isFamilyId(candidate.familyId) ? candidate.familyId : DEFAULT_APPEARANCE.familyId,
    sizeId: isSizeId(candidate.sizeId) ? candidate.sizeId : DEFAULT_APPEARANCE.sizeId,
  }
}

export function loadAppearance(): Appearance {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return DEFAULT_APPEARANCE
    return normalizeAppearance(JSON.parse(raw))
  } catch {
    // Corrupt JSON, or storage unavailable — fall back rather than throw.
    return DEFAULT_APPEARANCE
  }
}

export function saveAppearance(appearance: Appearance): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(appearance))
}

/** Writes the preference onto the document as CSS variables. `styles.css`
 * scales every font-size off `--font-scale` and sets the body's
 * `font-family` from `--font-family`, so this is the only place that has
 * to know how the two connect. */
export function applyAppearance(appearance: Appearance): void {
  const family = getFamilyPreset(appearance.familyId)
  const size = getSizePreset(appearance.sizeId)
  const root = document.documentElement
  root.style.setProperty('--font-family', family.stack)
  root.style.setProperty('--font-scale', String(size.scale))
}
