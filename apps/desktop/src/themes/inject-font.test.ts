import { afterEach, describe, expect, it } from 'vitest'

import { injectFontStylesheet } from './inject-font'

afterEach(() => {
  document.head.querySelectorAll('link[data-elidia-theme-font]').forEach(el => el.remove())
})

describe('injectFontStylesheet', () => {
  it('appends a stylesheet link for a new URL', () => {
    injectFontStylesheet('https://fonts.googleapis.com/css2?family=InjectTest')

    const links = document.head.querySelectorAll('link[data-elidia-theme-font]')

    expect(links.length).toBe(1)
    expect((links[0] as HTMLLinkElement).href).toContain('family=InjectTest')
    expect((links[0] as HTMLLinkElement).rel).toBe('stylesheet')
  })

  it('only injects a given URL once, even if called repeatedly', () => {
    const url = 'https://fonts.googleapis.com/css2?family=DedupTest'

    injectFontStylesheet(url)
    injectFontStylesheet(url)
    injectFontStylesheet(url)

    expect(document.head.querySelectorAll(`link[href="${url}"]`).length).toBe(1)
  })
})
