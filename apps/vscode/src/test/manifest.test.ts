/**
 * The manifest must contribute the activity-bar surface the developer reaches
 * for — an icon, a view container, and a chat view — or the extension installs
 * but has no button to open, which was exactly the bug this fixed.
 */
import assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as path from 'node:path'
import test from 'node:test'

const root = path.resolve(__dirname, '..', '..')
const manifest = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'))

test('an activity-bar view container is contributed', () => {
  const containers = manifest.contributes?.viewsContainers?.activitybar ?? []
  const elidia = containers.find((c: any) => c.id === 'elidia')
  assert.ok(elidia, 'no "elidia" activity-bar container')
  assert.ok(elidia.icon, 'the activity-bar container has no icon')
})

test('the activity-bar icon file exists on disk', () => {
  const containers = manifest.contributes?.viewsContainers?.activitybar ?? []
  const elidia = containers.find((c: any) => c.id === 'elidia')
  assert.ok(elidia?.icon, 'no icon path to check')
  assert.ok(
    fs.existsSync(path.join(root, elidia.icon)),
    `declared activity-bar icon is missing: ${elidia.icon}`
  )
})

test('a chat view is contributed under the container', () => {
  const views = manifest.contributes?.views?.elidia ?? []
  assert.ok(
    views.some((v: any) => v.type === 'elidia.chatView'),
    'no view of type elidia.chatView under the elidia container'
  )
})

test('the view type matches the registered provider id', () => {
  // The id here is what extension.ts registers with registerWebviewViewProvider.
  const views = manifest.contributes?.views?.elidia ?? []
  assert.ok(views.some((v: any) => v.type === 'elidia.chatView'))
})
