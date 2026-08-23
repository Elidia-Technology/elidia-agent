/**
 * The README must describe the extension that actually exists.
 *
 * When this extension moved from an HTTP backend to ACP, the commands and
 * settings changed and the README did not. It kept documenting
 * `elidia.backendPath`, `elidia.backendPort` and `elidia.autoStartBackend` —
 * three settings that no longer existed — and a "List Toolsets" command that had
 * been removed. Nobody would have noticed until a user followed it.
 *
 * Docs drift silently; a test does not.
 */
import assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as path from 'node:path'
import test from 'node:test'

const root = path.resolve(__dirname, '..', '..')
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'))
const readme = fs.readFileSync(path.join(root, 'README.md'), 'utf8')

test('every command is documented', () => {
  const undocumented = manifest.contributes.commands
    .map((c: any) => c.title)
    .filter((title: string) => !readme.includes(title))
  assert.deepEqual(undocumented, [], `commands missing from README: ${undocumented.join(', ')}`)
})

test('every setting is documented', () => {
  const settings = Object.keys(manifest.contributes.configuration.properties)
  const undocumented = settings.filter(s => !readme.includes(s))
  assert.deepEqual(undocumented, [], `settings missing from README: ${undocumented.join(', ')}`)
})

test('the README documents no setting that does not exist', () => {
  const declared = new Set(Object.keys(manifest.contributes.configuration.properties))
  const mentioned = new Set(readme.match(/elidia\.[a-zA-Z]+/g) ?? [])
  const stale = [...mentioned].filter(m => !declared.has(m))
  assert.deepEqual(stale, [], `README documents removed settings: ${stale.join(', ')}`)
})

test('the Marketplace listing has an icon that exists', () => {
  // Without this the listing renders a blank tile, which reads as abandoned.
  assert.ok(manifest.icon, 'package.json declares no icon')
  assert.ok(
    fs.existsSync(path.join(root, manifest.icon)),
    `declared icon is missing on disk: ${manifest.icon}`
  )
})

test('the install command includes the acp extra', () => {
  // `pip install elidia-agent-cli` without [acp] produces an extension that
  // cannot start, and the error is a ModuleNotFoundError deep in a child
  // process. The README must not send anyone down that path.
  assert.match(readme, /elidia-agent-cli\[acp\]/)
})
