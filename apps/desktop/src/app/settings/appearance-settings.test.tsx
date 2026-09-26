import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { AppearanceSettings } from './appearance-settings'

const FAMILY_KEY = 'elidia-desktop-font-family-v1'
const SIZE_KEY = 'elidia-desktop-font-size-v1'

beforeEach(() => {
  window.localStorage.clear()
  document.documentElement.style.removeProperty('--user-font-sans')
  document.documentElement.style.removeProperty('--user-font-scale')
})

afterEach(() => {
  cleanup()
})

describe('AppearanceSettings — Font section', () => {
  it('selects a font family, persisting it and applying the CSS var live', () => {
    render(<AppearanceSettings />)

    fireEvent.click(screen.getByRole('button', { name: /Inter/ }))

    expect(window.localStorage.getItem(FAMILY_KEY)).toBe('inter')
    expect(document.documentElement.style.getPropertyValue('--user-font-sans')).toContain('Inter')
  })

  it('selects a font size, persisting it and applying the CSS var live', () => {
    render(<AppearanceSettings />)

    fireEvent.click(screen.getByRole('button', { name: 'Larger' }))

    expect(window.localStorage.getItem(SIZE_KEY)).toBe('larger')
    expect(document.documentElement.style.getPropertyValue('--user-font-scale')).toBe('1.2')
  })

  it('resets font family + size to defaults and clears the CSS vars', () => {
    render(<AppearanceSettings />)

    fireEvent.click(screen.getByRole('button', { name: /Inter/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Larger' }))
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))

    expect(window.localStorage.getItem(FAMILY_KEY)).toBeNull()
    expect(window.localStorage.getItem(SIZE_KEY)).toBeNull()
    expect(document.documentElement.style.getPropertyValue('--user-font-sans')).toBe('')
    expect(document.documentElement.style.getPropertyValue('--user-font-scale')).toBe('')
  })
})
