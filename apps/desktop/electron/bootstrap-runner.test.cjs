const assert = require('node:assert/strict')
const test = require('node:test')

const { runBootstrap } = require('./bootstrap-runner.cjs')

test('runBootstrap bails immediately when the signal is already aborted', async () => {
  const controller = new AbortController()
  controller.abort()

  const events = []
  const result = await runBootstrap({
    installStamp: null,
    activeRoot: '/tmp/elidia-runner-test',
    sourceRepoRoot: null,
    elidiaHome: '/tmp/elidia-runner-test',
    logRoot: '/tmp/elidia-runner-test',
    onEvent: ev => events.push(ev),
    abortSignal: controller.signal
  })

  // Cancelled before any install script is spawned.
  assert.deepEqual(result, { ok: false, cancelled: true })
  assert.ok(
    events.some(ev => ev.type === 'failed' && /cancelled/i.test(ev.error)),
    'should emit a cancelled failure event'
  )
})

// ---------------------------------------------------------------------------
// First-launch bootstrap URL (release blocker)
// ---------------------------------------------------------------------------

const {
  installScriptUrl,
  PUBLIC_REPO,
  PUBLIC_FALLBACK_REF
} = require('./bootstrap-runner.cjs')

test('the install script is fetched from the public repo, not the renamed one', () => {
  // `elidia-agent-cli-v2` was the old name and now only 301-redirects;
  // raw.githubusercontent does not follow that reliably, so a build pointing
  // there 404s on first launch.
  assert.equal(PUBLIC_REPO, 'Elidia-Technology/elidia-agent')
  assert.ok(!installScriptUrl('abc123').includes('elidia-agent-cli-v2'))
})

test('a pinned commit is still preferred for reproducibility', () => {
  assert.ok(installScriptUrl('deadbeef').includes('/deadbeef/scripts/install.'))
})

test('there is a branch fallback for commits that are not public', () => {
  // Source of truth is GitLab. A build made from it pins a SHA that does NOT
  // exist on GitHub — the API answers 422 and raw answers 404 — which made
  // every locally built desktop dead on first launch for a user without
  // elidia_cli installed. downloadInstallScript retries on this ref.
  assert.equal(PUBLIC_FALLBACK_REF, 'master')
  assert.ok(installScriptUrl(PUBLIC_FALLBACK_REF).includes('/master/scripts/install.'))
})
