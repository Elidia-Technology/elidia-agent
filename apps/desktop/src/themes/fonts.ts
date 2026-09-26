/**
 * User font family + size preferences.
 *
 * These live on a separate CSS-variable layer (`--user-font-sans`,
 * `--user-font-scale`, wired in styles.css) that sits ON TOP of the active
 * theme's typography. `applyTheme` (context.tsx) never touches this layer,
 * so switching themes/skins can't wipe a user's font choice, and picking
 * "Theme default" simply removes the override and falls back to whatever
 * the active theme sets on `--dt-font-sans` / `--dt-base-size`.
 *
 * Persisted in localStorage next to the theme/mode keys (SKIN_KEY /
 * MODE_KEY in context.tsx) using the same naming convention.
 */

import { useCallback, useState } from 'react'

import { injectFontStylesheet } from './inject-font'

const FAMILY_KEY = 'elidia-desktop-font-family-v1'
const SIZE_KEY = 'elidia-desktop-font-size-v1'

export interface FontFamilyPreset {
  id: string
  label: string
  /** Short blurb shown under the family name in settings. */
  description: string
  /** CSS font-family stack. `null` means "Theme default" — no override. */
  stack: string | null
  /** Web font stylesheet to inject (same mechanism as theme `fontUrl`). */
  fontUrl?: string
}

export interface FontSizePreset {
  id: string
  label: string
  /** Multiplier applied on top of the active theme's base size. */
  scale: number
}

// Google Fonts stacks fall back through the same system faces the themes
// already use (see SYSTEM_SANS in presets.ts) if the web font fails to load.
const SYSTEM_FALLBACK = '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif'

export const FONT_FAMILY_PRESETS: FontFamilyPreset[] = [
  {
    id: 'theme-default',
    label: 'Theme default',
    description: 'Use the font that ships with the active theme.',
    stack: null
  },
  {
    id: 'system-ui',
    label: 'System UI',
    description: "Your OS's native interface font.",
    stack: `${SYSTEM_FALLBACK}`
  },
  {
    id: 'inter',
    label: 'Inter',
    description: 'Neutral, high-legibility grotesque.',
    stack: `"Inter", ${SYSTEM_FALLBACK}`,
    fontUrl: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap'
  },
  {
    id: 'roboto',
    label: 'Roboto',
    description: "Google's default UI typeface.",
    stack: `"Roboto", ${SYSTEM_FALLBACK}`,
    fontUrl: 'https://fonts.googleapis.com/css2?family=Roboto:wght@400;500;700&display=swap'
  },
  {
    id: 'atkinson-hyperlegible',
    label: 'Atkinson Hyperlegible',
    description: 'Designed for maximum legibility, low-vision friendly.',
    stack: `"Atkinson Hyperlegible", ${SYSTEM_FALLBACK}`,
    fontUrl: 'https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400;1,700&display=swap'
  },
  {
    id: 'serif',
    label: 'Serif',
    description: 'Georgia-based system serif — no download.',
    stack: 'Georgia, "Times New Roman", Times, serif'
  },
  {
    id: 'monospace',
    label: 'Monospace',
    description: "Reuses the active theme's code font everywhere.",
    stack: 'var(--dt-font-mono)'
  }
]

export const FONT_SIZE_PRESETS: FontSizePreset[] = [
  { id: 'small', label: 'Small', scale: 0.9 },
  { id: 'default', label: 'Default', scale: 1 },
  { id: 'large', label: 'Large', scale: 1.1 },
  { id: 'larger', label: 'Larger', scale: 1.2 },
  { id: 'largest', label: 'Largest', scale: 1.35 }
]

export const DEFAULT_FONT_FAMILY_ID = 'theme-default'
export const DEFAULT_FONT_SIZE_ID = 'default'

const familyById = (id: string): FontFamilyPreset | undefined => FONT_FAMILY_PRESETS.find(p => p.id === id)
const sizeById = (id: string): FontSizePreset | undefined => FONT_SIZE_PRESETS.find(p => p.id === id)

/** Falls back to the default id when the stored value is missing or unknown. */
const normalizeFamilyId = (id: string | null | undefined): string =>
  id && familyById(id) ? id : DEFAULT_FONT_FAMILY_ID

/** Falls back to the default id when the stored value is missing or unknown. */
const normalizeSizeId = (id: string | null | undefined): string => (id && sizeById(id) ? id : DEFAULT_FONT_SIZE_ID)

export function readFontFamilyId(): string {
  if (typeof window === 'undefined') {
    return DEFAULT_FONT_FAMILY_ID
  }

  return normalizeFamilyId(window.localStorage.getItem(FAMILY_KEY))
}

export function readFontSizeId(): string {
  if (typeof window === 'undefined') {
    return DEFAULT_FONT_SIZE_ID
  }

  return normalizeSizeId(window.localStorage.getItem(SIZE_KEY))
}

/**
 * Writes both `--user-font-sans` and `--user-font-scale` on the root
 * element for the given (already-persisted or about-to-be-persisted)
 * preference ids, normalizing anything unrecognised back to defaults.
 * Injects the family's web font, if any, the first time it's selected.
 */
export function applyFontPreferences(familyId: string, sizeId: string): void {
  if (typeof document === 'undefined') {
    return
  }

  const root = document.documentElement
  const family = familyById(normalizeFamilyId(familyId)) ?? (familyById(DEFAULT_FONT_FAMILY_ID) as FontFamilyPreset)
  const size = sizeById(normalizeSizeId(sizeId)) ?? (sizeById(DEFAULT_FONT_SIZE_ID) as FontSizePreset)

  if (family.stack) {
    root.style.setProperty('--user-font-sans', family.stack)
  } else {
    root.style.removeProperty('--user-font-sans')
  }

  if (size.scale !== 1) {
    root.style.setProperty('--user-font-scale', String(size.scale))
  } else {
    root.style.removeProperty('--user-font-scale')
  }

  if (family.fontUrl) {
    injectFontStylesheet(family.fontUrl)
  }
}

// Boot-time apply to avoid a flash of the wrong font/size before React
// mounts — mirrors the theme boot-time paint in context.tsx. Imported for
// its side effect from main.tsx, ahead of the first render.
if (typeof window !== 'undefined') {
  applyFontPreferences(readFontFamilyId(), readFontSizeId())
}

export interface FontPreferences {
  familyId: string
  sizeId: string
  family: FontFamilyPreset
  size: FontSizePreset
  setFamily: (id: string) => void
  setSize: (id: string) => void
  reset: () => void
}

/** React hook exposing the current font choice, plus persist+apply setters and a reset. */
export function useFontPreferences(): FontPreferences {
  const [familyId, setFamilyId] = useState(readFontFamilyId)
  const [sizeId, setSizeId] = useState(readFontSizeId)

  const setFamily = useCallback(
    (id: string) => {
      const next = normalizeFamilyId(id)
      window.localStorage.setItem(FAMILY_KEY, next)
      applyFontPreferences(next, sizeId)
      setFamilyId(next)
    },
    [sizeId]
  )

  const setSize = useCallback(
    (id: string) => {
      const next = normalizeSizeId(id)
      window.localStorage.setItem(SIZE_KEY, next)
      applyFontPreferences(familyId, next)
      setSizeId(next)
    },
    [familyId]
  )

  const reset = useCallback(() => {
    window.localStorage.removeItem(FAMILY_KEY)
    window.localStorage.removeItem(SIZE_KEY)
    applyFontPreferences(DEFAULT_FONT_FAMILY_ID, DEFAULT_FONT_SIZE_ID)
    setFamilyId(DEFAULT_FONT_FAMILY_ID)
    setSizeId(DEFAULT_FONT_SIZE_ID)
  }, [])

  return {
    familyId,
    sizeId,
    family: familyById(familyId) ?? (familyById(DEFAULT_FONT_FAMILY_ID) as FontFamilyPreset),
    size: sizeById(sizeId) ?? (sizeById(DEFAULT_FONT_SIZE_ID) as FontSizePreset),
    setFamily,
    setSize,
    reset
  }
}
