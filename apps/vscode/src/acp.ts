/**
 * ACP (Agent Client Protocol) client for the Elidia agent.
 *
 * V2 ships an editor interface already: `acp_adapter/` exposes the agent as the
 * console script `elidia-acp`, speaking JSON-RPC over stdio. That is what an
 * editor should talk to.
 *
 * An earlier draft of this extension spawned `elidia dashboard` and used HTTP,
 * mirroring the desktop. The desktop is right to do that — it renders the web
 * UI. An editor needs the agent, not the UI, and that design made a first launch
 * compile a React app (`tsc -b && vite build`) the extension never displays,
 * behind a web server, a port and a token, for what stdio does directly. It also
 * skipped edit approval and permission handling, which acp_adapter already
 * implements and which an agent editing your files genuinely needs.
 *
 * Verified handshake against the real adapter:
 *   protocolVersion: 1
 *   capabilities: loadSession, promptCapabilities.image,
 *                 sessionCapabilities.{fork,list,resume}
 */
import { ChildProcess, execFile, spawn } from 'node:child_process'
import { EventEmitter } from 'node:events'

/** JSON-RPC id -> pending resolver. */
interface Pending {
  resolve: (value: any) => void
  reject: (err: Error) => void
}

export class AcpUnavailableError extends Error {}

export interface AcpLaunch {
  command: string
  args: string[]
  label: string
}

function run(command: string, args: string[], timeout = 20_000): Promise<{ ok: boolean; stdout: string; stderr: string }> {
  return new Promise(resolve => {
    execFile(command, args, { timeout }, (err, stdout, stderr) =>
      resolve({ ok: !err, stdout: String(stdout), stderr: String(stderr) })
    )
  })
}

function commandExists(command: string): Promise<boolean> {
  return new Promise(resolve => {
    const probe = process.platform === 'win32' ? 'where' : 'which'
    execFile(probe, [command], { timeout: 5000 }, err => resolve(!err))
  })
}

/**
 * True when this Python can actually run the adapter.
 *
 * `agent-client-protocol` is an OPTIONAL extra. Without it the adapter starts,
 * logs "Starting elidia-agent ACP adapter", and then dies on
 * `ModuleNotFoundError: No module named 'acp'` — so checking that elidia_cli
 * imports is not enough to conclude the adapter will run.
 */
async function pythonCanRunAcp(python: string): Promise<boolean> {
  const probe = await run(python, ['-c', 'import acp_adapter, acp'])
  return probe.ok
}

/**
 * True when this command starts an adapter that STAYS UP.
 *
 * Existence is not function, and this is the second time that distinction bit:
 * `elidia-acp` was on PATH from an older install whose environment lacks the
 * optional `acp` package, so it started, logged, and died on
 * `ModuleNotFoundError: No module named 'acp'` with exit 1. A healthy adapter
 * blocks waiting for stdin, so "still alive after a moment" is the signal.
 */
function staysUp(command: string, args: string[], settleMs = 3000): Promise<boolean> {
  return new Promise(resolve => {
    let child: ChildProcess
    try {
      child = spawn(command, args, { stdio: ['pipe', 'ignore', 'ignore'] })
    } catch {
      resolve(false)
      return
    }
    let settled = false
    const finish = (ok: boolean) => {
      if (settled) return
      settled = true
      try {
        child.kill('SIGTERM')
      } catch {
        // Already gone.
      }
      resolve(ok)
    }
    child.on('error', () => finish(false))
    child.on('exit', () => finish(false))
    setTimeout(() => finish(true), settleMs)
  })
}

/** Find a way to launch the ACP adapter, or null. */
export async function resolveAcp(configuredPath: string): Promise<AcpLaunch | null> {
  if (configuredPath) {
    return { command: configuredPath, args: [], label: `configured (${configuredPath})` }
  }
  if (await commandExists('elidia-acp') && await staysUp('elidia-acp', [])) {
    return { command: 'elidia-acp', args: [], label: 'elidia-acp on PATH' }
  }
  for (const python of ['python3', 'python']) {
    if (await commandExists(python) && await pythonCanRunAcp(python)) {
      return { command: python, args: ['-m', 'acp_adapter'], label: `${python} -m acp_adapter` }
    }
  }
  return null
}

/**
 * Distinguish "no Elidia at all" from "Elidia without the acp extra", because
 * the fix is different and the second is easy to get wrong.
 */
export async function diagnoseMissingAcp(): Promise<string> {
  for (const python of ['python3', 'python']) {
    if (!(await commandExists(python))) continue
    const hasCli = await run(python, ['-c', 'import elidia_cli'])
    if (hasCli.ok) {
      return (
        'Elidia is installed but the ACP extra is missing. ' +
        'Install it with `pip install "elidia-agent-cli[acp]"`.'
      )
    }
  }
  return (
    'No Elidia agent found. Install it with `pip install "elidia-agent-cli[acp]"`, ' +
    'or set `elidia.acpPath` to the `elidia-acp` executable.'
  )
}

/**
 * Newline-delimited JSON-RPC over the adapter's stdio.
 *
 * Emits:
 *   'notification' (method, params) — session/update chunks and the like
 *   'request'      (id, method, params) — server->client calls the editor must
 *                  answer, e.g. permission and edit approval
 *   'exit'         (code)
 */
export class AcpClient extends EventEmitter {
  private child: ChildProcess | null = null
  private nextId = 1
  private pending = new Map<number, Pending>()
  private buffer = ''
  private readonly log: (line: string) => void

  constructor(log: (line: string) => void) {
    super()
    this.log = log
  }

  get running(): boolean {
    return this.child !== null && !this.child.killed
  }

  async start(configuredPath: string, cwd: string): Promise<void> {
    if (this.running) return

    const launch = await resolveAcp(configuredPath)
    if (!launch) throw new AcpUnavailableError(await diagnoseMissingAcp())

    this.log(`starting ACP adapter via ${launch.label}`)
    const child = spawn(launch.command, launch.args, {
      cwd,
      stdio: ['pipe', 'pipe', 'pipe'],
      env: { ...process.env }
    })
    this.child = child

    child.stdout?.setEncoding('utf8')
    child.stdout?.on('data', chunk => this.onStdout(String(chunk)))
    child.stderr?.setEncoding('utf8')
    child.stderr?.on('data', chunk => this.log(String(chunk).trimEnd()))

    child.on('error', err => {
      this.child = null
      this.failAllPending(new AcpUnavailableError(`Could not start the ACP adapter: ${err.message}`))
    })
    child.on('exit', code => {
      this.child = null
      this.emit('exit', code)
      this.failAllPending(new AcpUnavailableError(`The ACP adapter exited with code ${code}.`))
    })
  }

  private failAllPending(err: Error): void {
    for (const { reject } of this.pending.values()) reject(err)
    this.pending.clear()
  }

  private onStdout(chunk: string): void {
    this.buffer += chunk
    let index: number
    while ((index = this.buffer.indexOf('\n')) >= 0) {
      const line = this.buffer.slice(0, index).trim()
      this.buffer = this.buffer.slice(index + 1)
      if (!line) continue
      try {
        this.dispatch(JSON.parse(line))
      } catch {
        // The adapter also logs to stdout in some paths; a non-JSON line is
        // information, not a protocol violation.
        this.log(line)
      }
    }
  }

  private dispatch(message: any): void {
    if (typeof message.id === 'number' && (message.result !== undefined || message.error !== undefined)) {
      const pending = this.pending.get(message.id)
      if (!pending) return
      this.pending.delete(message.id)
      if (message.error) {
        pending.reject(new Error(message.error?.message ?? JSON.stringify(message.error)))
      } else {
        pending.resolve(message.result)
      }
      return
    }
    if (message.method && message.id !== undefined) {
      // Server -> client request. The editor must answer, e.g. to approve a
      // file edit. Leaving these unanswered would hang the agent mid-turn.
      this.emit('request', message.id, message.method, message.params)
      return
    }
    if (message.method) {
      this.emit('notification', message.method, message.params)
    }
  }

  private send(payload: unknown): void {
    if (!this.child?.stdin) throw new AcpUnavailableError('The ACP adapter is not running.')
    this.child.stdin.write(JSON.stringify(payload) + '\n')
  }

  request(method: string, params: unknown = {}, timeoutMs = 300_000): Promise<any> {
    const id = this.nextId++
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id)
        reject(new Error(`ACP request ${method} timed out after ${Math.round(timeoutMs / 1000)}s`))
      }, timeoutMs)

      this.pending.set(id, {
        resolve: value => {
          clearTimeout(timer)
          resolve(value)
        },
        reject: err => {
          clearTimeout(timer)
          reject(err)
        }
      })

      try {
        this.send({ jsonrpc: '2.0', id, method, params })
      } catch (err) {
        clearTimeout(timer)
        this.pending.delete(id)
        reject(err as Error)
      }
    })
  }

  /** Answer a server -> client request (permission, edit approval). */
  respond(id: number, result: unknown): void {
    this.send({ jsonrpc: '2.0', id, result })
  }

  notify(method: string, params: unknown = {}): void {
    this.send({ jsonrpc: '2.0', method, params })
  }

  stop(): void {
    if (this.child && !this.child.killed) {
      this.log('stopping ACP adapter')
      this.child.kill('SIGTERM')
    }
    this.child = null
    this.failAllPending(new AcpUnavailableError('The ACP adapter was stopped.'))
  }
}
