/** Chat webview markup. Kept in its own module so extension.ts stays about wiring. */

/**
 * The webview runs with a strict CSP: no inline styles or remote resources, and
 * scripts only from the extension's own source. `cspSource` is supplied by VS
 * Code for the active webview.
 */
export function renderChatHtml(cspSource: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy"
      content="default-src 'none'; img-src ${cspSource} data:; style-src ${cspSource} 'unsafe-inline'; script-src ${cspSource} 'unsafe-inline';">
<title>Elidia Agent</title>
<style>
  /* Everything is expressed in VS Code theme variables so the panel belongs to
     whatever theme the user actually runs, light or dark, instead of imposing
     a palette that fights it. */
  * { box-sizing: border-box; }
  body {
    font-family: var(--vscode-font-family);
    font-size: var(--vscode-font-size);
    color: var(--vscode-foreground);
    background: var(--vscode-editor-background);
    margin: 0; height: 100vh;
    display: flex; flex-direction: column;
  }

  #log { flex: 1; overflow-y: auto; padding: 16px 16px 8px; scroll-behavior: smooth; }

  /* Empty state: tell a first-time user what this can do rather than showing
     a blank rectangle. */
  #empty { max-width: 42ch; margin: 12vh auto 0; text-align: center; opacity: .85; }
  #empty h2 { font-size: 15px; font-weight: 600; margin: 0 0 6px; }
  #empty p  { font-size: 12.5px; line-height: 1.6; color: var(--vscode-descriptionForeground); margin: 0 0 14px; }
  .hint {
    display: inline-block; margin: 3px; padding: 4px 9px; font-size: 11.5px;
    border: 1px solid var(--vscode-panel-border); border-radius: 999px;
    color: var(--vscode-descriptionForeground); cursor: pointer;
  }
  .hint:hover { color: var(--vscode-foreground); border-color: var(--vscode-focusBorder); }

  .turn { margin-bottom: 16px; animation: rise .18s ease-out; }
  @keyframes rise { from { opacity: 0; transform: translateY(3px); } to { opacity: 1; transform: none; } }
  @media (prefers-reduced-motion: reduce) {
    .turn { animation: none; }
    #log { scroll-behavior: auto; }
  }

  .role {
    display: flex; align-items: center; gap: 6px;
    font-size: 10.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .07em;
    color: var(--vscode-descriptionForeground); margin-bottom: 5px;
  }
  .dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: .55; }
  .turn.you .role   { color: var(--vscode-textLink-foreground); }
  .turn.elidia .role{ color: var(--vscode-charts-green, var(--vscode-textLink-activeForeground)); }

  .body {
    white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.55;
    padding-left: 12px; border-left: 2px solid var(--vscode-panel-border);
  }
  .turn.you .body { border-left-color: var(--vscode-textLink-foreground); opacity: .95; }

  /* Thinking and tool activity are secondary: visible, never competing with
     the answer. */
  .turn.meta .body {
    font-size: 12px; font-style: italic;
    color: var(--vscode-descriptionForeground);
    border-left-style: dashed;
  }

  .caret::after {
    content: '▌'; margin-left: 1px; opacity: .7;
    animation: blink 1.1s step-end infinite;
  }
  @keyframes blink { 50% { opacity: 0; } }

  #composer {
    display: flex; gap: 8px; align-items: flex-end;
    padding: 10px 12px 12px; border-top: 1px solid var(--vscode-panel-border);
    background: var(--vscode-editor-background);
  }
  #input {
    flex: 1; resize: none; min-height: 34px; max-height: 40vh;
    padding: 8px 10px; font-family: inherit; font-size: inherit; line-height: 1.45;
    color: var(--vscode-input-foreground); background: var(--vscode-input-background);
    border: 1px solid var(--vscode-input-border, transparent); border-radius: 6px;
  }
  #input:focus { outline: 1px solid var(--vscode-focusBorder); outline-offset: -1px; }
  button {
    padding: 8px 14px; cursor: pointer; border: none; border-radius: 6px;
    font-family: inherit; font-size: 12.5px; font-weight: 500;
    color: var(--vscode-button-foreground); background: var(--vscode-button-background);
  }
  button:hover { background: var(--vscode-button-hoverBackground); }
  #stop { display: none; background: var(--vscode-inputValidation-errorBorder, #c33); }
  body.busy #stop { display: inline-block; }
  body.busy #send { display: none; }
  #meta {
    padding: 0 14px 8px; font-size: 11px; color: var(--vscode-descriptionForeground);
    display: flex; justify-content: space-between;
  }
</style>
</head>
<body>
  <div id="log">
    <div id="empty">
      <h2>Elidia Agent</h2>
      <p>Ask about this workspace, or select code and use Explain or Fix from the right-click menu.</p>
      <div>
        <span class="hint">Explain this file</span>
        <span class="hint">Find the bug in my selection</span>
        <span class="hint">Write tests for this</span>
      </div>
    </div>
  </div>
  <div id="meta"><span id="state"></span><span id="hintkeys">Enter to send · Shift+Enter for a new line</span></div>
  <form id="composer">
    <textarea id="input" rows="1" placeholder="Ask Elidia…" autocomplete="off"></textarea>
    <button type="submit" id="send">Send</button>
    <button type="button" id="stop" title="Stop the current turn">Stop</button>
  </form>
<script>
  const vscode = acquireVsCodeApi()
  const log = document.getElementById('log')
  const form = document.getElementById('composer')
  const input = document.getElementById('input')
  const empty = document.getElementById('empty')
  const state = document.getElementById('state')

  function clearEmpty() { if (empty) empty.remove() }

  function addTurn(role, text, kind) {
    clearEmpty()
    const turn = document.createElement('div')
    turn.className = 'turn ' + (kind || role)
    const label = document.createElement('div')
    label.className = 'role'
    const dot = document.createElement('span')
    dot.className = 'dot'
    label.append(dot, document.createTextNode(role))
    const body = document.createElement('div')
    body.className = 'body'
    // textContent, never innerHTML: model output is untrusted and must not be
    // able to inject markup into the panel.
    body.textContent = text
    turn.append(label, body)
    log.append(turn)
    log.scrollTop = log.scrollHeight
    return body
  }

  let liveBody = null

  function send(text) {
    if (!text.trim()) return
    addTurn('you', text.trim())
    input.value = ''
    input.style.height = 'auto'
    vscode.postMessage({ type: 'send', text: text.trim() })
  }

  form.addEventListener('submit', e => { e.preventDefault(); send(input.value) })

  // Enter sends; Shift+Enter is a newline — the convention people already have
  // from every other chat surface.
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(input.value) }
  })
  input.addEventListener('input', () => {
    input.style.height = 'auto'
    input.style.height = Math.min(input.scrollHeight, window.innerHeight * 0.4) + 'px'
  })

  document.querySelectorAll('.hint').forEach(h =>
    h.addEventListener('click', () => { input.value = h.textContent; input.focus() }))

  document.getElementById('stop').addEventListener('click', () =>
    vscode.postMessage({ type: 'cancel' }))

  window.addEventListener('message', event => {
    const m = event.data
    switch (m.type) {
      case 'user': addTurn('you', m.text); break
      case 'start':
        liveBody = addTurn('elidia', '')
        liveBody.classList.add('caret')
        document.body.classList.add('busy')
        state.textContent = 'thinking…'
        break
      case 'chunk':
        if (!liveBody) { liveBody = addTurn('elidia', ''); liveBody.classList.add('caret') }
        liveBody.textContent += m.text
        log.scrollTop = log.scrollHeight
        state.textContent = 'responding…'
        break
      case 'thought': addTurn('thinking', m.text, 'meta'); break
      case 'tool':
        addTurn('tool', m.text, 'meta')
        state.textContent = m.text
        break
      case 'end':
        if (liveBody) liveBody.classList.remove('caret')
        liveBody = null
        document.body.classList.remove('busy')
        state.textContent = ''
        break
    }
  })

  input.focus()
</script>
</body>
</html>`
}
