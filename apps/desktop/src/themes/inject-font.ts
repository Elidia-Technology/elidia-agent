/**
 * Shared `<link rel="stylesheet">` injector for web fonts.
 *
 * Both theme presets (`typography.fontUrl` in `presets.ts`, applied by
 * `context.tsx`) and user font family presets (`fonts.ts`) route through
 * this single helper so a given stylesheet URL is only ever injected once,
 * regardless of which caller requested it first.
 */

const INJECTED_FONT_URLS = new Set<string>()

/** Appends a `<link>` for `url` to `<head>` unless it was already injected. */
export function injectFontStylesheet(url: string): void {
  if (typeof document === 'undefined' || INJECTED_FONT_URLS.has(url)) {
    return
  }

  const link = document.createElement('link')
  link.rel = 'stylesheet'
  link.href = url
  link.dataset.elidiaThemeFont = 'true'
  document.head.appendChild(link)
  INJECTED_FONT_URLS.add(url)
}
