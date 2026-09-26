import { describe, expect, it, vi } from 'vitest'

vi.mock('@streamdown/mermaid', () => ({
  createMermaidPlugin: vi.fn((options: unknown) => ({
    getMermaid: () => ({ initialize: () => undefined, render: async () => ({ svg: '' }) }),
    language: 'mermaid',
    name: 'mermaid',
    options,
    type: 'diagram'
  }))
}))

import { createMermaidPlugin } from '@streamdown/mermaid'

import { createDesktopMermaidPlugin } from './mermaid'

describe('createDesktopMermaidPlugin', () => {
  it('renders model-authored diagrams with strict security and the light theme', () => {
    createDesktopMermaidPlugin('light')
    expect(createMermaidPlugin).toHaveBeenLastCalledWith({ config: { securityLevel: 'strict', theme: 'default' } })
  })

  it('switches the diagram theme to dark in dark mode, still strict', () => {
    createDesktopMermaidPlugin('dark')
    expect(createMermaidPlugin).toHaveBeenLastCalledWith({ config: { securityLevel: 'strict', theme: 'dark' } })
  })
})
