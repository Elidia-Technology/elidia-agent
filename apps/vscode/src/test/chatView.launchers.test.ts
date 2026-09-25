/**
 * The empty chat state must carry working launchers for the standalone Desktop
 * app and the CLI — not just hint chips. This locks the two buttons (and the
 * messages they post) so a refactor cannot silently drop them.
 */
import assert from 'node:assert/strict'
import test from 'node:test'

import { renderChatHtml } from '../chatView'

const ASSETS = {
  bannerLight: 'https://webview.example/banner-light.png',
  bannerDark: 'https://webview.example/banner-dark.png',
  mark: 'https://webview.example/elidia-mark.png'
}

const html = () => renderChatHtml('https://webview.example', ASSETS)

test('the empty state has a launchers container', () => {
  assert.ok(html().includes('id="launchers"'), 'the launchers container is missing')
})

test('the empty state offers the Desktop app and the CLI', () => {
  const markup = html()
  assert.ok(markup.includes('id="launch-desktop"'), 'the Desktop launcher button is missing')
  assert.ok(markup.includes('id="launch-cli"'), 'the CLI launcher button is missing')
  assert.ok(markup.includes('Open Desktop App'), 'the Desktop button has no label')
  assert.ok(markup.includes('Open CLI'), 'the CLI button has no label')
})

test('each launcher posts a distinct message to the extension', () => {
  const markup = html()
  assert.ok(markup.includes("vscode.postMessage({ type: 'launchDesktop' })"),
    'the Desktop button does not post launchDesktop')
  assert.ok(markup.includes("vscode.postMessage({ type: 'launchCli' })"),
    'the CLI button does not post launchCli')
})
