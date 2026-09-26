import { act, render, renderHook } from '@testing-library/react'
import { useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  applyFontPreferences,
  DEFAULT_FONT_FAMILY_ID,
  DEFAULT_FONT_SIZE_ID,
  FONT_FAMILY_PRESETS,
  FONT_SIZE_PRESETS,
  readFontFamilyId,
  readFontSizeId,
  useFontPreferences
} from './fonts'

const FAMILY_KEY = 'elidia-desktop-font-family-v1'
const SIZE_KEY = 'elidia-desktop-font-size-v1'

function resetDom() {
  window.localStorage.clear()
  document.documentElement.style.removeProperty('--user-font-sans')
  document.documentElement.style.removeProperty('--user-font-scale')
  document.head.querySelectorAll('link[data-elidia-theme-font]').forEach(el => el.remove())
}

beforeEach(resetDom)
afterEach(resetDom)

describe('font presets', () => {
  it('have unique ids and include the documented defaults', () => {
    const familyIds = FONT_FAMILY_PRESETS.map(p => p.id)
    const sizeIds = FONT_SIZE_PRESETS.map(p => p.id)

    expect(new Set(familyIds).size).toBe(familyIds.length)
    expect(new Set(sizeIds).size).toBe(sizeIds.length)
    expect(familyIds).toContain(DEFAULT_FONT_FAMILY_ID)
    expect(sizeIds).toContain(DEFAULT_FONT_SIZE_ID)
  })

  it('only "Theme default" has a null stack (every other family overrides it)', () => {
    const nullStackIds = FONT_FAMILY_PRESETS.filter(p => p.stack === null).map(p => p.id)

    expect(nullStackIds).toEqual([DEFAULT_FONT_FAMILY_ID])
  })

  it('sizes are all positive, with "default" fixed at 1', () => {
    for (const size of FONT_SIZE_PRESETS) {
      expect(size.scale).toBeGreaterThan(0)
    }

    expect(FONT_SIZE_PRESETS.find(p => p.id === DEFAULT_FONT_SIZE_ID)?.scale).toBe(1)
  })
})

describe('readFontFamilyId / readFontSizeId', () => {
  it('return defaults when nothing is stored', () => {
    expect(readFontFamilyId()).toBe(DEFAULT_FONT_FAMILY_ID)
    expect(readFontSizeId()).toBe(DEFAULT_FONT_SIZE_ID)
  })

  it('normalize unknown/corrupt stored values back to defaults', () => {
    window.localStorage.setItem(FAMILY_KEY, 'not-a-real-font-id')
    window.localStorage.setItem(SIZE_KEY, 'huge')

    expect(readFontFamilyId()).toBe(DEFAULT_FONT_FAMILY_ID)
    expect(readFontSizeId()).toBe(DEFAULT_FONT_SIZE_ID)
  })

  it('round-trip a valid stored preference', () => {
    window.localStorage.setItem(FAMILY_KEY, 'inter')
    window.localStorage.setItem(SIZE_KEY, 'large')

    expect(readFontFamilyId()).toBe('inter')
    expect(readFontSizeId()).toBe('large')
  })
})

describe('applyFontPreferences', () => {
  it('sets --user-font-sans for a family with a stack, and removes it for the theme default', () => {
    applyFontPreferences('inter', 'default')
    expect(document.documentElement.style.getPropertyValue('--user-font-sans')).toContain('Inter')

    applyFontPreferences('theme-default', 'default')
    expect(document.documentElement.style.getPropertyValue('--user-font-sans')).toBe('')
  })

  it('sets --user-font-scale for a non-default size, and removes it at scale 1', () => {
    applyFontPreferences('theme-default', 'larger')
    expect(document.documentElement.style.getPropertyValue('--user-font-scale')).toBe('1.2')

    applyFontPreferences('theme-default', 'default')
    expect(document.documentElement.style.getPropertyValue('--user-font-scale')).toBe('')
  })

  it('normalizes unrecognised ids passed directly, instead of throwing', () => {
    expect(() => applyFontPreferences('does-not-exist', 'also-missing')).not.toThrow()
    expect(document.documentElement.style.getPropertyValue('--user-font-sans')).toBe('')
    expect(document.documentElement.style.getPropertyValue('--user-font-scale')).toBe('')
  })

  it('injects a family web font stylesheet exactly once, no matter how often it is applied', () => {
    // Uses a family no other test in this file selects: `injectFontStylesheet`
    // dedupes by URL in a module-scope Set that (correctly) outlives DOM
    // resets, so re-using an already-injected family here would always
    // read back 0 new links instead of exercising the dedupe path.
    applyFontPreferences('atkinson-hyperlegible', 'default')
    applyFontPreferences('atkinson-hyperlegible', 'default')
    applyFontPreferences('atkinson-hyperlegible', 'large')

    const links = Array.from(document.head.querySelectorAll('link[data-elidia-theme-font]')).filter(link =>
      (link as HTMLLinkElement).href.includes('Atkinson')
    )

    expect(links.length).toBe(1)
  })
})

describe('useFontPreferences', () => {
  it('persists and applies family/size changes live, and resets to defaults', () => {
    const { result } = renderHook(() => useFontPreferences())

    act(() => result.current.setFamily('roboto'))
    expect(result.current.familyId).toBe('roboto')
    expect(window.localStorage.getItem(FAMILY_KEY)).toBe('roboto')
    expect(document.documentElement.style.getPropertyValue('--user-font-sans')).toContain('Roboto')

    act(() => result.current.setSize('larger'))
    expect(result.current.sizeId).toBe('larger')
    expect(window.localStorage.getItem(SIZE_KEY)).toBe('larger')
    expect(document.documentElement.style.getPropertyValue('--user-font-scale')).toBe('1.2')

    act(() => result.current.reset())
    expect(result.current.familyId).toBe(DEFAULT_FONT_FAMILY_ID)
    expect(result.current.sizeId).toBe(DEFAULT_FONT_SIZE_ID)
    expect(window.localStorage.getItem(FAMILY_KEY)).toBeNull()
    expect(window.localStorage.getItem(SIZE_KEY)).toBeNull()
    expect(document.documentElement.style.getPropertyValue('--user-font-sans')).toBe('')
    expect(document.documentElement.style.getPropertyValue('--user-font-scale')).toBe('')
  })
})

describe('theme re-apply', () => {
  it('does not clear the user font vars when the active theme/skin changes', async () => {
    applyFontPreferences('inter', 'larger')
    expect(document.documentElement.style.getPropertyValue('--user-font-sans')).toContain('Inter')
    expect(document.documentElement.style.getPropertyValue('--user-font-scale')).toBe('1.2')

    const { ThemeProvider, useTheme } = await import('./context')
    let setTheme: (name: string) => void = () => undefined

    // Captures the setter via an effect (a side effect), not during render,
    // so this test harness itself stays react-compiler-clean.
    function Probe({ onReady }: { onReady: (fn: (name: string) => void) => void }) {
      const theme = useTheme()

      useEffect(() => onReady(theme.setTheme), [onReady, theme.setTheme])

      return null
    }

    render(
      <ThemeProvider>
        <Probe
          onReady={fn => {
            setTheme = fn
          }}
        />
      </ThemeProvider>
    )

    act(() => setTheme('midnight'))

    expect(document.documentElement.style.getPropertyValue('--user-font-sans')).toContain('Inter')
    expect(document.documentElement.style.getPropertyValue('--user-font-scale')).toBe('1.2')
  })
})
