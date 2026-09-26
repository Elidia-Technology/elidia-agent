import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { DEFAULT_APPEARANCE, getFamilyPreset, getSizePreset } from '../lib/appearance'
import { Settings } from './Settings'

function root() {
  return document.documentElement
}

// No @testing-library/jest-dom in this workspace, so assertions read the
// DOM directly instead of via matchers like toHaveAttribute.
function pressed(element: HTMLElement): string | null {
  return element.getAttribute('aria-pressed')
}

beforeEach(() => {
  localStorage.clear()
  root().style.removeProperty('--font-family')
  root().style.removeProperty('--font-scale')
})

afterEach(() => {
  cleanup()
})

describe('Settings', () => {
  it('renders a back button that calls onBack', () => {
    let backCalls = 0
    render(<Settings onBack={() => (backCalls += 1)} />)
    fireEvent.click(screen.getByLabelText('Back to sessions'))
    expect(backCalls).toBe(1)
  })

  it('marks the default appearance as selected on first render', () => {
    render(<Settings onBack={() => {}} />)
    expect(pressed(screen.getByRole('button', { name: /System/ }))).toBe('true')
    expect(pressed(screen.getByRole('button', { name: /Default/ }))).toBe('true')
  })

  it('choosing a font family updates --font-family and localStorage, and deselects the previous choice', () => {
    render(<Settings onBack={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: /Serif/ }))

    expect(root().style.getPropertyValue('--font-family')).toBe(getFamilyPreset('serif').stack)
    expect(pressed(screen.getByRole('button', { name: /Serif/ }))).toBe('true')
    expect(pressed(screen.getByRole('button', { name: /System/ }))).toBe('false')
    expect(JSON.parse(localStorage.getItem('elidia.appearance')!)).toEqual({
      familyId: 'serif',
      sizeId: 'default',
    })
  })

  it('choosing a text size updates --font-scale and localStorage', () => {
    render(<Settings onBack={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: /Larger/ }))

    expect(root().style.getPropertyValue('--font-scale')).toBe(String(getSizePreset('larger').scale))
    expect(JSON.parse(localStorage.getItem('elidia.appearance')!)).toEqual({
      familyId: 'system',
      sizeId: 'larger',
    })
  })

  it('reset to defaults restores system family and default size after changes', () => {
    render(<Settings onBack={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: /Monospace/ }))
    fireEvent.click(screen.getByRole('button', { name: /Largest/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Reset to defaults' }))

    expect(root().style.getPropertyValue('--font-family')).toBe(getFamilyPreset('system').stack)
    expect(root().style.getPropertyValue('--font-scale')).toBe('1')
    expect(JSON.parse(localStorage.getItem('elidia.appearance')!)).toEqual(DEFAULT_APPEARANCE)
    expect(pressed(screen.getByRole('button', { name: /System/ }))).toBe('true')
    expect(pressed(screen.getByRole('button', { name: /Default/ }))).toBe('true')
  })
})
