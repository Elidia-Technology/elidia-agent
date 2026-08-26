/**
 * Elidia Agent for VS Code (V2) — an ACP client.
 *
 * The agent is reached over the Agent Client Protocol (`elidia-acp`, stdio
 * JSON-RPC), which V2 already ships in `acp_adapter/`. See src/acp.ts for why
 * this replaced an earlier HTTP-to-the-dashboard design.
 *
 * ACP is what makes the editor-shaped parts possible: streamed message and
 * thought chunks, live tool-call updates, and — the reason it matters most —
 * permission and edit-approval requests answered through VS Code's own prompts,
 * so the agent cannot touch your files without you seeing it.
 */
import * as vscode from 'vscode'

import { AcpClient, AcpUnavailableError } from './acp'
import { renderChatHtml } from './chatView'

let client: AcpClient | null = null
let sessionId: string | null = null
let output: vscode.OutputChannel
let status: vscode.StatusBarItem
let chatPanel: vscode.WebviewPanel | null = null
// Captured at activation. openChatPanel needs it to build webview URIs for the
// banner and avatar, and a webview cannot load anything from disk without a
// localResourceRoots entry derived from it.
let extensionUri: vscode.Uri

function config() {
  return vscode.workspace.getConfiguration('elidia')
}

function workspaceCwd(): string {
  return vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? process.cwd()
}

/**
 * Answer a server -> client request.
 *
 * Permission and edit-approval requests block the agent mid-turn, so an
 * unanswered one hangs the conversation. Anything not explicitly allowed is
 * refused rather than left pending.
 */
async function handleServerRequest(id: number, method: string, params: any): Promise<void> {
  if (!client) return

  if (method.includes('request_permission') || method.includes('requestPermission')) {
    const title: string =
      params?.tool_call?.title ?? params?.toolCall?.title ?? params?.title ?? 'run a tool'
    const options: any[] = params?.options ?? []

    const allowOption = options.find((o: any) => /allow/i.test(o?.kind ?? o?.name ?? o?.optionId ?? ''))
    const rejectOption = options.find((o: any) => /reject|deny/i.test(o?.kind ?? o?.name ?? o?.optionId ?? ''))

    const choice = await vscode.window.showWarningMessage(
      `Elidia wants to ${title}.`,
      { modal: true },
      'Allow',
      'Reject'
    )
    const picked = choice === 'Allow' ? allowOption : rejectOption
    client.respond(id, {
      outcome: {
        outcome: choice === 'Allow' ? 'selected' : 'cancelled',
        optionId: picked?.optionId ?? picked?.id ?? null
      }
    })
    output.appendLine(`permission: ${title} -> ${choice ?? 'Reject'}`)
    return
  }

  // Unknown server request: answer rather than leave the agent waiting.
  output.appendLine(`unhandled ACP request: ${method}`)
  client.respond(id, {})
}

function handleNotification(method: string, params: any): void {
  if (!method.includes('session') || !params) return
  const update = params.update ?? params
  const kind: string = update?.sessionUpdate ?? update?.session_update ?? ''

  const textOf = (block: any): string =>
    typeof block === 'string' ? block : (block?.text ?? '')

  if (kind.includes('agent_message_chunk')) {
    chatPanel?.webview.postMessage({ type: 'chunk', text: textOf(update.content) })
  } else if (kind.includes('agent_thought_chunk')) {
    chatPanel?.webview.postMessage({ type: 'thought', text: textOf(update.content) })
  } else if (kind.includes('tool_call')) {
    const title = update?.title ?? update?.toolCallId ?? 'tool'
    const statusText = update?.status ?? ''
    chatPanel?.webview.postMessage({ type: 'tool', text: `${title} ${statusText}`.trim() })
  }
}

async function ensureClient(): Promise<AcpClient> {
  if (client?.running && sessionId) return client

  if (!client) {
    client = new AcpClient(line => output.appendLine(line))
    client.on('notification', handleNotification)
    client.on('request', handleServerRequest)
    client.on('exit', () => {
      sessionId = null
      status.text = '$(error) Elidia'
    })
  }

  status.text = '$(sync~spin) Elidia: starting'
  status.show()
  try {
    await client.start(config().get<string>('acpPath', '') || '', workspaceCwd())

    await client.request('initialize', {
      protocolVersion: 1,
      clientCapabilities: { fs: { readTextFile: false, writeTextFile: false } }
    })

    const session = await client.request('session/new', { cwd: workspaceCwd(), mcpServers: [] })
    sessionId = session?.sessionId ?? session?.session_id ?? null
    if (!sessionId) throw new Error('The ACP adapter did not return a session id.')

    status.text = '$(check) Elidia'
    output.appendLine(`session ${sessionId} ready`)
  } catch (err) {
    status.text = '$(error) Elidia'
    throw err
  }
  return client
}

async function reportError(err: unknown): Promise<void> {
  const message = err instanceof Error ? err.message : String(err)
  output.appendLine(`error: ${message}`)
  const actions = err instanceof AcpUnavailableError ? ['Show Log'] : ['Show Log']
  const choice = await vscode.window.showErrorMessage(`Elidia: ${message}`, ...actions)
  if (choice === 'Show Log') output.show(true)
}

function selectionContext(): { text: string; language: string; file: string } | null {
  const editor = vscode.window.activeTextEditor
  if (!editor || editor.selection.isEmpty) return null
  return {
    text: editor.document.getText(editor.selection),
    language: editor.document.languageId,
    file: vscode.workspace.asRelativePath(editor.document.uri)
  }
}

function openChatPanel(): vscode.WebviewPanel {
  if (chatPanel) {
    chatPanel.reveal(vscode.ViewColumn.Beside)
    return chatPanel
  }
  chatPanel = vscode.window.createWebviewPanel(
    'elidia.chat',
    'Elidia Agent',
    vscode.ViewColumn.Beside,
    {
      enableScripts: true,
      retainContextWhenHidden: true,
      // Without this the webview cannot load anything from disk, and the
      // banner and avatar would silently render as broken images. Scoped to
      // media/ so the extension exposes its own artwork and nothing else.
      localResourceRoots: [vscode.Uri.joinPath(extensionUri, 'media')]
    }
  )
  const mediaUri = (file: string) =>
    chatPanel!.webview.asWebviewUri(vscode.Uri.joinPath(extensionUri, 'media', file)).toString()

  chatPanel.webview.html = renderChatHtml(chatPanel.webview.cspSource, {
    bannerLight: mediaUri('banner-light.png'),
    bannerDark: mediaUri('banner-dark.png'),
    mark: mediaUri('elidia-mark.png')
  })
  chatPanel.webview.onDidReceiveMessage(async message => {
    if (message?.type === 'send' && typeof message.text === 'string' && message.text.trim()) {
      try {
        await ask(message.text.trim(), false)
      } catch (err) {
        await reportError(err)
      }
    } else if (message?.type === 'cancel') {
      if (client?.running && sessionId) {
        client.notify('session/cancel', { sessionId })
        output.appendLine('cancel requested')
      }
    }
  })
  chatPanel.onDidDispose(() => {
    chatPanel = null
  })
  return chatPanel
}

/** Send a prompt; replies arrive as streamed notifications. */
async function ask(prompt: string, echo = true): Promise<void> {
  const acp = await ensureClient()
  const panel = openChatPanel()
  if (echo) panel.webview.postMessage({ type: 'user', text: prompt })
  panel.webview.postMessage({ type: 'start' })

  try {
    await acp.request('session/prompt', {
      sessionId,
      prompt: [{ type: 'text', text: prompt }]
    })
  } finally {
    panel.webview.postMessage({ type: 'end' })
  }
}

export function activate(context: vscode.ExtensionContext): void {
  extensionUri = context.extensionUri
  output = vscode.window.createOutputChannel('Elidia Agent')
  status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100)
  status.command = 'elidia.chat'
  status.tooltip = 'Elidia Agent'
  context.subscriptions.push(output, status)

  const register = (id: string, run: () => Promise<void>) =>
    context.subscriptions.push(
      vscode.commands.registerCommand(id, async () => {
        try {
          await run()
        } catch (err) {
          await reportError(err)
        }
      })
    )

  register('elidia.chat', async () => {
    await ensureClient()
    openChatPanel()
  })

  register('elidia.explain', async () => {
    const selection = selectionContext()
    if (!selection) {
      vscode.window.showInformationMessage('Elidia: select some code first.')
      return
    }
    await ask(
      `Explain this ${selection.language} from ${selection.file}:\n\n` +
        '```' + selection.language + '\n' + selection.text + '\n```'
    )
  })

  register('elidia.fix', async () => {
    const selection = selectionContext()
    if (!selection) {
      vscode.window.showInformationMessage('Elidia: select some code first.')
      return
    }
    await ask(
      `Find and fix the problem in this ${selection.language} from ${selection.file}. ` +
        'Show the corrected code and say what was wrong:\n\n' +
        '```' + selection.language + '\n' + selection.text + '\n```'
    )
  })

  register('elidia.selectModel', async () => {
    const acp = await ensureClient()
    const listed = await acp.request('session/list', {}).catch(() => null)
    const models: any[] = listed?.models ?? []
    const items = models.map((m: any) => String(m?.modelId ?? m?.name ?? m))
    if (!items.length) {
      vscode.window.showInformationMessage(
        'Elidia: the adapter reported no models for this session.'
      )
      return
    }
    const picked = await vscode.window.showQuickPick(items, { placeHolder: 'Select a model' })
    if (!picked) return
    await acp.request('session/set_model', { sessionId, modelId: picked })
    vscode.window.showInformationMessage(`Elidia: model set to ${picked}.`)
  })

  register('elidia.cancel', async () => {
    if (!client?.running || !sessionId) {
      vscode.window.showInformationMessage('Elidia: nothing is running.')
      return
    }
    client.notify('session/cancel', { sessionId })
    vscode.window.showInformationMessage('Elidia: cancel requested.')
  })

  register('elidia.restart', async () => {
    client?.stop()
    client = null
    sessionId = null
    await ensureClient()
    vscode.window.showInformationMessage('Elidia: agent restarted.')
  })

  register('elidia.showLog', async () => {
    output.show(true)
  })
}

export function deactivate(): void {
  // The adapter is our child process; leaving it running would leak an agent
  // per closed window.
  client?.stop()
  client = null
  sessionId = null
}
