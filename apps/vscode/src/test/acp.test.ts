/**
 * Tests for the ACP client.
 *
 * They drive a fake adapter over stdio rather than mocking the client's own
 * internals, so the framing, dispatch and server->client request path are
 * exercised the way the real adapter would exercise them.
 */
import assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import test from 'node:test'

import { AcpClient, resolveAcp } from '../acp'

/**
 * Write an EXECUTABLE fake adapter that speaks ACP-shaped JSON-RPC on stdio.
 *
 * Executable, with a shebang, on purpose: the client is then launched through
 * its real `start()` via the `acpPath` setting. An earlier version of this
 * harness monkey-patched `start()`, which meant the tests never exercised the
 * spawn wiring — and promptly "failed" a test about a dying adapter because the
 * HARNESS had not reproduced the exit handling, not because the client was
 * wrong. A harness that diverges from the code path is worse than no harness.
 */
function fakeAdapter(body: string): string {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'acp-')), 'adapter.js')
  fs.writeFileSync(file, '#!/usr/bin/env node\n' + body)
  fs.chmodSync(file, 0o755)
  return file
}

function clientFor(_script: string): AcpClient {
  return new AcpClient(() => {})
}

test('a response resolves the matching request', async () => {
  const script = fakeAdapter(`
    let buf = ''
    process.stdin.on('data', d => {
      buf += d
      let i
      while ((i = buf.indexOf('\\n')) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 1)
        if (!line.trim()) continue
        const msg = JSON.parse(line)
        process.stdout.write(JSON.stringify({
          jsonrpc: '2.0', id: msg.id,
          result: { protocolVersion: 1, echoed: msg.method }
        }) + '\\n')
      }
    })
  `)
  const client = clientFor(script)
  await client.start(script, process.cwd())
  const result = await client.request('initialize', { protocolVersion: 1 })
  assert.equal(result.protocolVersion, 1)
  assert.equal(result.echoed, 'initialize')
  client.stop()
})

test('an error response rejects with the message', async () => {
  const script = fakeAdapter(`
    process.stdin.on('data', d => {
      const msg = JSON.parse(String(d).trim())
      process.stdout.write(JSON.stringify({
        jsonrpc: '2.0', id: msg.id, error: { code: -32000, message: 'session not found' }
      }) + '\\n')
    })
  `)
  const client = clientFor(script)
  await client.start(script, process.cwd())
  await assert.rejects(() => client.request('session/prompt', {}), /session not found/)
  client.stop()
})

test('notifications are emitted, not treated as responses', async () => {
  const script = fakeAdapter(`
    process.stdin.on('data', d => {
      const msg = JSON.parse(String(d).trim())
      process.stdout.write(JSON.stringify({
        jsonrpc: '2.0', method: 'session/update',
        params: { update: { sessionUpdate: 'agent_message_chunk', content: { text: 'hi' } } }
      }) + '\\n')
      process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: msg.id, result: {} }) + '\\n')
    })
  `)
  const client = clientFor(script)
  const seen: Array<[string, any]> = []
  client.on('notification', (m, p) => seen.push([m, p]))
  await client.start(script, process.cwd())
  await client.request('session/prompt', {})
  assert.equal(seen.length, 1)
  assert.equal(seen[0][0], 'session/update')
  assert.equal(seen[0][1].update.content.text, 'hi')
  client.stop()
})

test('a server->client request is surfaced so the editor can answer it', async () => {
  // Permission requests block the agent mid-turn. If the client treated one as
  // a notification and never replied, the conversation would hang forever.
  // The adapter asks permission mid-turn, waits for the editor's answer, and
  // only then completes the prompt — the real ordering. If the client treated
  // the request as a notification and never replied, this would hang.
  const script = fakeAdapter(`
    let promptId = null
    let buf = ''
    process.stdin.on('data', d => {
      buf += d
      let i
      while ((i = buf.indexOf('\\n')) >= 0) {
        const line = buf.slice(0, i); buf = buf.slice(i + 1)
        if (!line.trim()) continue
        const msg = JSON.parse(line)
        if (msg.method === 'session/prompt') {
          promptId = msg.id
          process.stdout.write(JSON.stringify({
            jsonrpc: '2.0', id: 99, method: 'session/request_permission',
            params: { title: 'edit README.md' }
          }) + '\\n')
        } else if (msg.id === 99 && msg.result !== undefined) {
          process.stdout.write(JSON.stringify({
            jsonrpc: '2.0', id: promptId,
            result: { stopReason: 'end_turn', approved: msg.result }
          }) + '\\n')
        }
      }
    })
  `)
  const client = clientFor(script)
  const requests: Array<[number, string, any]> = []
  client.on('request', (id, method, params) => {
    requests.push([id, method, params])
    client.respond(id, { outcome: { outcome: 'selected' } })
  })
  await client.start(script, process.cwd())

  const result = await client.request('session/prompt', {}, 15_000)

  assert.equal(requests.length, 1)
  assert.equal(requests[0][1], 'session/request_permission')
  assert.equal(requests[0][2].title, 'edit README.md')
  // The turn completed, which only happens if the editor's answer got back.
  assert.equal(result.stopReason, 'end_turn')
  assert.deepEqual(result.approved.outcome, { outcome: 'selected' })
  client.stop()
})

test('multiple JSON objects in one chunk are all dispatched', async () => {
  // stdio delivers arbitrary chunk boundaries; two messages can arrive glued.
  const script = fakeAdapter(`
    process.stdin.on('data', d => {
      const msg = JSON.parse(String(d).trim())
      process.stdout.write(
        JSON.stringify({ jsonrpc: '2.0', method: 'a', params: {} }) + '\\n' +
        JSON.stringify({ jsonrpc: '2.0', method: 'b', params: {} }) + '\\n' +
        JSON.stringify({ jsonrpc: '2.0', id: msg.id, result: {} }) + '\\n'
      )
    })
  `)
  const client = clientFor(script)
  const methods: string[] = []
  client.on('notification', m => methods.push(m))
  await client.start(script, process.cwd())
  await client.request('x', {})
  assert.deepEqual(methods, ['a', 'b'])
  client.stop()
})

test('a split JSON line is buffered until complete', async () => {
  const script = fakeAdapter(`
    process.stdin.on('data', d => {
      const msg = JSON.parse(String(d).trim())
      const payload = JSON.stringify({ jsonrpc: '2.0', id: msg.id, result: { ok: true } })
      process.stdout.write(payload.slice(0, 10))
      setTimeout(() => process.stdout.write(payload.slice(10) + '\\n'), 50)
    })
  `)
  const client = clientFor(script)
  await client.start(script, process.cwd())
  const result = await client.request('x', {})
  assert.equal(result.ok, true)
  client.stop()
})

test('a dying adapter rejects in-flight requests instead of hanging', async () => {
  const script = fakeAdapter(`process.stdin.on('data', () => process.exit(3))`)
  const client = clientFor(script)
  await client.start(script, process.cwd())
  await assert.rejects(() => client.request('x', {}, 8000), /exited with code 3/)
})

test('non-JSON stdout is logged, not treated as a protocol error', async () => {
  const script = fakeAdapter(`
    process.stdin.on('data', d => {
      const msg = JSON.parse(String(d).trim())
      process.stdout.write('Starting elidia-agent ACP adapter\\n')
      process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id: msg.id, result: { ok: 1 } }) + '\\n')
    })
  `)
  const logged: string[] = []
  const client = new AcpClient(l => logged.push(l))
  await client.start(script, process.cwd())
  const result = await client.request('x', {})
  assert.equal(result.ok, 1)
  assert.ok(logged.some(l => l.includes('Starting elidia-agent ACP adapter')))
  client.stop()
})

test('a configured path is used verbatim', async () => {
  const resolved = await resolveAcp('/opt/elidia-acp')
  assert.equal(resolved?.command, '/opt/elidia-acp')
  assert.deepEqual(resolved?.args, [])
})
