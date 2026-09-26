/**
 * Mermaid diagram support for rendered markdown (chat + file previews).
 *
 * One place builds the plugin so every surface renders diagrams the same way:
 * - `securityLevel: 'strict'` — diagram source comes from model output, so no
 *   HTML labels and no click handlers are allowed into the rendered SVG.
 * - the diagram theme follows the app's resolved light/dark mode.
 */
import { createMermaidPlugin, type DiagramPlugin } from '@streamdown/mermaid'
import { useMemo } from 'react'

import { useTheme } from '@/themes/context'

export function createDesktopMermaidPlugin(mode: 'light' | 'dark'): DiagramPlugin {
  return createMermaidPlugin({
    config: {
      securityLevel: 'strict',
      theme: mode === 'dark' ? 'dark' : 'default'
    }
  })
}

/** The Mermaid plugin for the current light/dark mode (stable per mode). */
export function useMermaidPlugin(): DiagramPlugin {
  const { resolvedMode } = useTheme()

  return useMemo(() => createDesktopMermaidPlugin(resolvedMode), [resolvedMode])
}
