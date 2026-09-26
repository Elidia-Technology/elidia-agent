import { beforeEach, describe, expect, it } from 'vitest'

import {
  DEFAULT_APPEARANCE,
  FAMILY_PRESETS,
  SIZE_PRESETS,
  applyAppearance,
  getFamilyPreset,
  getSizePreset,
  loadAppearance,
  normalizeAppearance,
  saveAppearance,
} from './appearance'

beforeEach(() => {
  localStorage.clear()
  document.documentElement.style.removeProperty('--font-family')
  document.documentElement.style.removeProperty('--font-scale')
})

describe('presets', () => {
  it('has one family preset per id, each with a non-empty CSS stack', () => {
    const ids = FAMILY_PRESETS.map(p => p.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids.sort()).toEqual(['monospace', 'rounded', 'serif', 'system'])
    for (const preset of FAMILY_PRESETS) {
      expect(preset.stack.length).toBeGreaterThan(0)
      expect(preset.label.length).toBeGreaterThan(0)
    }
  })

  it('has the five required size presets with the specified scales', () => {
    const byId = Object.fromEntries(SIZE_PRESETS.map(p => [p.id, p.scale]))
    expect(byId).toEqual({
      small: 0.9,
      default: 1,
      large: 1.1,
      larger: 1.2,
      largest: 1.35,
    })
  })

  it('defaults to the system family at 1x scale', () => {
    expect(DEFAULT_APPEARANCE).toEqual({ familyId: 'system', sizeId: 'default' })
  })

  it('getFamilyPreset/getSizePreset fall back to the default for an unknown id', () => {
    // These functions are typed to FontFamilyId/FontSizeId, but normalizeAppearance
    // is what actually receives untrusted input; this exercises the same fallback
    // path via a cast, since a corrupt store is the only way to get here at runtime.
    expect(getFamilyPreset('nonexistent' as never)).toEqual(FAMILY_PRESETS[0])
    expect(getSizePreset('nonexistent' as never)).toEqual(SIZE_PRESETS[1])
  })
})

describe('normalizeAppearance', () => {
  it('passes through a valid appearance unchanged', () => {
    expect(normalizeAppearance({ familyId: 'serif', sizeId: 'large' })).toEqual({
      familyId: 'serif',
      sizeId: 'large',
    })
  })

  it('normalizes each field independently on partial corruption', () => {
    expect(normalizeAppearance({ familyId: 'serif', sizeId: 'not-a-size' })).toEqual({
      familyId: 'serif',
      sizeId: 'default',
    })
    expect(normalizeAppearance({ familyId: 'not-a-family', sizeId: 'large' })).toEqual({
      familyId: 'system',
      sizeId: 'large',
    })
  })

  it('normalizes non-object, null, and undefined input to the defaults', () => {
    expect(normalizeAppearance(null)).toEqual(DEFAULT_APPEARANCE)
    expect(normalizeAppearance(undefined)).toEqual(DEFAULT_APPEARANCE)
    expect(normalizeAppearance('garbage')).toEqual(DEFAULT_APPEARANCE)
    expect(normalizeAppearance(42)).toEqual(DEFAULT_APPEARANCE)
    expect(normalizeAppearance([])).toEqual(DEFAULT_APPEARANCE)
  })
})

describe('loadAppearance', () => {
  it('returns the defaults when nothing is stored', () => {
    expect(loadAppearance()).toEqual(DEFAULT_APPEARANCE)
  })

  it('returns the defaults when the stored value is not valid JSON', () => {
    localStorage.setItem('elidia.appearance', '{not json')
    expect(loadAppearance()).toEqual(DEFAULT_APPEARANCE)
  })

  it('returns a normalized value when the stored JSON has an invalid field', () => {
    localStorage.setItem('elidia.appearance', JSON.stringify({ familyId: 'rounded', sizeId: 99 }))
    expect(loadAppearance()).toEqual({ familyId: 'rounded', sizeId: 'default' })
  })
})

describe('persistence round-trip', () => {
  it('saveAppearance followed by loadAppearance returns the same value', () => {
    const appearance = { familyId: 'monospace', sizeId: 'largest' } as const
    saveAppearance(appearance)
    expect(loadAppearance()).toEqual(appearance)
  })
})

describe('applyAppearance', () => {
  it('sets --font-family and --font-scale on the document root', () => {
    applyAppearance({ familyId: 'serif', sizeId: 'large' })
    const root = document.documentElement
    expect(root.style.getPropertyValue('--font-family')).toBe(getFamilyPreset('serif').stack)
    expect(root.style.getPropertyValue('--font-scale')).toBe('1.1')
  })

  it('applying the default appearance sets scale to 1', () => {
    applyAppearance(DEFAULT_APPEARANCE)
    expect(document.documentElement.style.getPropertyValue('--font-scale')).toBe('1')
  })
})
