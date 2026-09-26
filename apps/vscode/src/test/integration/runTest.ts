/**
 * Integration test runner: launches a real VS Code with this extension loaded in
 * an isolated, throwaway profile and runs ./suite inside its extension host.
 *
 * Set VSCODE_EXECUTABLE_PATH to use an installed VS Code; otherwise
 * @vscode/test-electron downloads the current stable build.
 */
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { runTests } from '@vscode/test-electron'

async function main(): Promise<void> {
  const extensionDevelopmentPath = path.resolve(__dirname, '../../..')
  const extensionTestsPath = path.resolve(__dirname, './suite')
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'elidia-vscode-it-'))
  await runTests({
    vscodeExecutablePath: process.env.VSCODE_EXECUTABLE_PATH || undefined,
    extensionDevelopmentPath,
    extensionTestsPath,
    launchArgs: ['--disable-extensions', `--user-data-dir=${userDataDir}`, '--skip-welcome', '--skip-release-notes']
  })
}

main().catch(err => {
  console.error('Integration tests failed:', err)
  process.exit(1)
})
