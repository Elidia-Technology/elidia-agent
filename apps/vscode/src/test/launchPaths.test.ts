/**
 * Tests for the platform detection behind the Desktop/CLI launchers.
 *
 * These are the pure functions — no `vscode` import — so the "is it installed,
 * and where?" logic is exercised with plain `node --test`.
 */
import assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import test from 'node:test'

import { commandPath, desktopCandidates, DOWNLOAD_URL, firstExisting } from '../launchPaths'

test('DOWNLOAD_URL is the canonical releases page', () => {
  assert.equal(DOWNLOAD_URL, 'https://github.com/Elidia-Technology/elidia-agent/releases/latest')
})

test('desktopCandidates returns non-empty, non-blank install paths', () => {
  const candidates = desktopCandidates({})
  assert.ok(Array.isArray(candidates), 'desktopCandidates did not return an array')
  assert.ok(candidates.length > 0, 'no install locations were listed')
  assert.ok(candidates.every(c => typeof c === 'string' && c.length > 0))
})

test('desktopCandidates lists the Applications folder on macOS', { skip: process.platform !== 'darwin' }, () => {
  assert.ok(desktopCandidates({}).includes('/Applications/Elidia Agent.app'))
})

test('firstExisting picks the first candidate that exists', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'elidia-launch-'))
  const missing = path.join(dir, 'missing')
  const present = path.join(dir, 'present')
  fs.writeFileSync(present, '')
  assert.equal(firstExisting([missing, present]), present)
})

test('firstExisting returns null when no candidate exists', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'elidia-launch-'))
  assert.equal(firstExisting([path.join(dir, 'nope1'), path.join(dir, 'nope2')]), null)
})

test('firstExisting ignores blank candidates', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'elidia-launch-'))
  const present = path.join(dir, 'present')
  fs.writeFileSync(present, '')
  assert.equal(firstExisting(['', present]), present)
})

test('commandPath returns null for a command that does not exist', () => {
  assert.equal(commandPath('elidia-definitely-not-a-real-command-xyz'), null)
})
