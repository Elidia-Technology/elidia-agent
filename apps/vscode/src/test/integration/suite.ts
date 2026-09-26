/**
 * Runs inside a real VS Code extension host. Verifies what a user needs after
 * installing: a visible way into the chat (activity-bar container + sidebar
 * view + commands), and that "Elidia: Open Chat" opens the chat window even
 * when the agent cannot start.
 */
import * as assert from 'node:assert/strict'
import * as vscode from 'vscode'

const EXTENSION_ID = 'ElidiaTechnology.elidia-agent-vscode'

async function waitFor(check: () => boolean, what: string, timeoutMs = 20000): Promise<void> {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (check()) return
    await new Promise(resolve => setTimeout(resolve, 200))
  }
  throw new Error(`Timed out waiting for: ${what}`)
}

async function step(name: string, fn: () => Promise<void>): Promise<void> {
  await fn()
  console.log(`  ✓ ${name}`)
}

export async function run(): Promise<void> {
  const extension = vscode.extensions.getExtension(EXTENSION_ID)
  assert.ok(extension, `${EXTENSION_ID} is loaded`)

  await step('activity-bar container "elidia" is contributed', async () => {
    const containers = extension.packageJSON?.contributes?.viewsContainers?.activitybar ?? []
    assert.ok(containers.some((c: any) => c.id === 'elidia'), 'activitybar container elidia')
  })

  await step('clicking the activity-bar icon activates the extension', async () => {
    await vscode.commands.executeCommand('workbench.view.extension.elidia')
    await waitFor(() => extension.isActive, 'extension activation')
  })

  await step('chat, launcher and view commands are registered', async () => {
    const commands = await vscode.commands.getCommands(true)
    for (const id of ['elidia.chat', 'elidia.launchDesktop', 'elidia.launchCli', 'elidia.restart', 'elidia.chatView.focus']) {
      assert.ok(commands.includes(id), `command ${id} is registered`)
    }
  })

  await step('the sidebar chat view opens', async () => {
    await vscode.commands.executeCommand('elidia.chatView.focus')
  })

  await step('"Elidia: Open Chat" opens the chat window even when the agent cannot start', async () => {
    await vscode.workspace
      .getConfiguration('elidia')
      .update('acpPath', '/nonexistent/elidia-acp', vscode.ConfigurationTarget.Global)
    // Not awaited: with no agent the command ends in an error notification that
    // waits for the user to dismiss it. The window must already be open.
    void vscode.commands.executeCommand('elidia.chat')
    await waitFor(
      () => vscode.window.tabGroups.all.some(group => group.tabs.some(tab => tab.label === 'Elidia Agent')),
      'an "Elidia Agent" chat tab'
    )
  })
}
