/**
 * Launch (or help install) the standalone Elidia Agent surfaces — the Desktop
 * app and the CLI — from inside VS Code.
 *
 * "Launch" is literal: if the target is already installed we start it. If it is
 * not, we open the canonical download page and say so. We never silently no-op:
 * every branch either starts the target or tells the user what we could not find.
 *
 * Path/process detection is in `launchPaths.ts` (no `vscode` import, so it is
 * unit-testable); this module owns the `vscode`-dependent side effects.
 */

import { spawn } from 'node:child_process'
import * as vscode from 'vscode'

import { commandPath, desktopCandidates, DOWNLOAD_URL, firstExisting } from './launchPaths'

const MAC = process.platform === 'darwin'

/** Start the Desktop app detached from VS Code so closing the editor keeps it. */
function startProcess(exe: string): void {
  if (MAC && exe.endsWith('.app')) {
    // `open -a` asks LaunchServices to start the bundled app; spawning the
    // inner Mach-O directly would skip the normal app lifecycle.
    spawn('open', ['-a', exe], { detached: true, stdio: 'ignore' }).unref()
    return
  }
  spawn(exe, [], { detached: true, stdio: 'ignore' }).unref()
}

async function openDownloadPage(): Promise<void> {
  await vscode.env.openExternal(vscode.Uri.parse(DOWNLOAD_URL))
}

/**
 * Launch the Desktop app, or open its download page when it is not installed.
 * Returns a short human-readable status used in the confirmation message.
 */
export async function launchDesktop(): Promise<string> {
  const found = firstExisting(desktopCandidates())
  if (found) {
    startProcess(found)
    return `Launched Elidia Agent (${found})`
  }

  await openDownloadPage()
  return 'Elidia Agent desktop app is not installed — opened the download page.'
}

/**
 * Launch the CLI in an integrated terminal, or open its download page when the
 * `elidia` executable is not on PATH. Returns a short human-readable status.
 */
export async function launchCli(): Promise<string> {
  const elidiaPath = commandPath('elidia')
  if (elidiaPath) {
    const terminal = vscode.window.createTerminal({
      name: 'Elidia Agent',
      shellPath: elidiaPath
    })
    terminal.show()
    return `Launched Elidia CLI (${elidiaPath})`
  }

  await openDownloadPage()
  return 'Elidia CLI is not installed — opened the download page.'
}
