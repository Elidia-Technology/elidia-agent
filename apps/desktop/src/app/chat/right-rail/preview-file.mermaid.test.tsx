import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const renderDiagram = vi.fn<(id: string, source: string) => Promise<{ svg: string }>>()

// The real hook is memoized per light/dark mode, so it returns one stable
// plugin object; the mock must too, or the render effect re-runs every render.
const stablePlugin = {
  getMermaid: () => ({ initialize: () => undefined, render: (id: string, source: string) => renderDiagram(id, source) }),
  language: 'mermaid',
  name: 'mermaid',
  type: 'diagram'
}

vi.mock('@/lib/mermaid', () => ({
  useMermaidPlugin: () => stablePlugin
}))

import { MarkdownPreview } from './preview-file'

const MERMAID_DOC = '# Flow\n\n```mermaid\ngraph TD; A-->B\n```\n'

describe('MarkdownPreview mermaid fences', () => {
  beforeEach(() => {
    renderDiagram.mockReset()
  })

  it('renders a ```mermaid fence as the diagram SVG', async () => {
    renderDiagram.mockResolvedValue({ svg: '<svg data-testid="diagram"><g></g></svg>' })
    const { container } = render(<MarkdownPreview text={MERMAID_DOC} />)

    await waitFor(() => expect(container.querySelector('.preview-mermaid svg')).not.toBeNull())
    expect(renderDiagram).toHaveBeenCalledTimes(1)
    expect(renderDiagram.mock.calls[0][1]).toBe('graph TD; A-->B')
  })

  it('shows the error and the diagram source when Mermaid rejects it', async () => {
    renderDiagram.mockRejectedValue(new Error('Parse error on line 1'))
    render(<MarkdownPreview text={MERMAID_DOC} />)

    expect(await screen.findByText(/Diagram could not be rendered: Parse error on line 1/)).not.toBeNull()
  })

  it('leaves other code fences to the syntax highlighter', async () => {
    render(<MarkdownPreview text={'```json\n{"a": 1}\n```\n'} />)

    await waitFor(() => expect(renderDiagram).not.toHaveBeenCalled())
  })
})
