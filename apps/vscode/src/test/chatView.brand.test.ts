import assert from 'node:assert/strict'
import test from 'node:test'

import { renderChatHtml } from '../chatView'

const ASSETS = {
  bannerLight: 'https://webview.example/banner-light.png',
  bannerDark: 'https://webview.example/banner-dark.png',
  mark: 'https://webview.example/elidia-mark.png'
}

const render = () => renderChatHtml('https://webview.example', ASSETS)

test('the empty state carries both banner variants', () => {
  const html = render()

  assert.ok(html.includes(ASSETS.bannerLight), 'light banner missing')
  assert.ok(html.includes(ASSETS.bannerDark), 'dark banner missing')
  assert.ok(html.includes('class="banner banner-light"'))
  assert.ok(html.includes('class="banner banner-dark"'))
})

test('the banner switches on the VS Code theme class, not a guess', () => {
  const html = render()

  // VS Code stamps vscode-light / vscode-dark / vscode-high-contrast on <body>.
  // That is the only signal that cannot disagree with the surrounding panel.
  assert.ok(html.includes('body.vscode-dark #empty .banner-light'))
  assert.ok(html.includes('body.vscode-dark #empty .banner-dark'))
  assert.ok(html.includes('body.vscode-high-contrast #empty .banner-dark'))
})

test('only the visible banner carries alt text', () => {
  const html = render()

  // A screen reader should hear the product name once, not once per variant.
  assert.ok(html.includes('alt="Elidia Agent"'), 'the visible banner has no alt text')
  assert.ok(html.includes('aria-hidden="true"'), 'the duplicate is not hidden from a11y')
})

test('the assistant turn is given the Elidia mark', () => {
  const html = render()

  assert.ok(html.includes(`const ELIDIA_MARK = ${JSON.stringify(ASSETS.mark)}`),
    'the mark URI never reaches the panel script')
  assert.ok(html.includes("mark.className = 'avatar'"))
  assert.ok(html.includes('mark.src = ELIDIA_MARK'))
})

test('the user turn is a glyph, never a fabricated face', () => {
  const html = render()

  // This panel has no identity for the person using the editor.
  assert.ok(html.includes("glyph.className = 'avatar avatar-user'"))
  // The \u25CF escape resolves at compile time, so the emitted panel carries
  // the character itself rather than the escape sequence.
  assert.ok(html.includes("glyph.textContent = '\u25CF'"),
    'the glyph character is missing')
  assert.ok(!html.includes('avatar-user"><img'), 'a user image was drawn')
})

test('avatars are built with DOM calls, not injected markup', () => {
  const html = render()

  // Everything touching model output stays on createElement/textContent so a
  // reply cannot inject markup into the panel.
  assert.ok(html.includes("document.createElement('img')"))
  assert.ok(html.includes('body.textContent = text'))
  assert.ok(!html.includes('body.innerHTML'), 'innerHTML reached the message body')
})

test('the CSP still admits the extension origin and nothing wider', () => {
  const html = render()

  assert.ok(html.includes("default-src 'none'"), 'the deny-by-default base is gone')
  assert.ok(html.includes('img-src https://webview.example data:'),
    'images are not scoped to the webview origin')
  assert.ok(!html.includes('img-src *'), 'the image policy was widened to any origin')
})
