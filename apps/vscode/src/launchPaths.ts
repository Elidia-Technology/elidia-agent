/**
 * Platform paths and process detection for the standalone Elidia surfaces.
 *
 * Kept free of any `vscode` import so these pure functions can be unit-tested
 * with plain `node --test`. The `vscode`-dependent launching lives in
 * `launcher.ts`.
 */

import { spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { homedir } from 'node:os'
import { join } from 'node:path'

/** Canonical download hub — desktop installers and CLI artefacts live here. */
export const DOWNLOAD_URL = 'https://github.com/Elidia-Technology/elidia-agent/releases/latest'

const WIN = process.platform === 'win32'
const MAC = process.platform === 'darwin'

/**
 * Candidate install locations for the Desktop app, most likely first.
 * Kept as a pure function of the environment so tests can assert the list
 * without touching a real machine.
 */
export function desktopCandidates(env: NodeJS.ProcessEnv = process.env): string[] {
  if (MAC) {
    return [
      '/Applications/Elidia Agent.app',
      join(homedir(), 'Applications', 'Elidia Agent.app')
    ]
  }

  if (WIN) {
    const la = env.LOCALAPPDATA ?? join(homedir(), 'AppData', 'Local')
    const pf = env.ProgramFiles ?? 'C:\\Program Files'
    const pfx = env['ProgramFiles(x86)'] ?? 'C:\\Program Files (x86)'
    return [
      join(la, 'Programs', 'Elidia Agent', 'Elidia.exe'),
      join(la, 'Programs', 'elidia', 'Elidia.exe'),
      join(pf, 'Elidia Agent', 'Elidia.exe'),
      join(pf, 'Elidia', 'Elidia.exe'),
      join(pfx, 'Elidia Agent', 'Elidia.exe'),
      join(pfx, 'Elidia', 'Elidia.exe')
    ]
  }

  return [
    '/opt/Elidia Agent/elidia',
    join(homedir(), '.local', 'bin', 'elidia-desktop'),
    '/usr/bin/elidia-desktop'
  ]
}

/** First candidate that exists on disk, or `null` when none do. */
export function firstExisting(candidates: string[]): string | null {
  return candidates.find(p => p.length > 0 && existsSync(p)) ?? null
}

/** Resolve a command name to an absolute path via `where` (Windows) / `which`. */
export function commandPath(command: string): string | null {
  const probe = WIN ? 'where' : 'which'
  const res = spawnSync(probe, [command], { encoding: 'utf8', timeout: 5000 })
  if (res.status !== 0) return null
  const first = (res.stdout ?? '')
    .split(/\r?\n/)
    .map(s => s.trim())
    .find(s => s.length > 0)
  return first ?? null
}
