<p align="center">
  <img src="media/icon.png" width="112" alt="Elidia Agent">
</p>

<h1 align="center">Elidia Agent for VS Code</h1>

<p align="center">
  Chat with Elidia, and explain or fix the code you have selected —
  running against your own agent, on your machine.
</p>

---

## What it does

**Chat that streams.** Replies arrive token by token, with the agent's tool
calls shown as they happen, so you can see what it is doing rather than waiting
at a spinner.

**Explain and Fix on a selection.** Select code, right-click, and get an
explanation or a corrected version — the file and language go along with it, so
the answer is about *your* code and not a generic snippet.

**It asks before it acts.** When the agent wants to use a tool that touches your
files, VS Code shows a modal asking you first. Anything you do not explicitly
allow is refused. This is not an add-on: it is part of the protocol the
extension speaks.

**Stop a runaway turn.** The Stop button cancels the current turn without
restarting the agent or losing the conversation.

**Switch models.** Pick from whatever models your Elidia install offers.

## Requirements

```bash
pip install "elidia-agent-cli[acp]"
```

The `[acp]` part matters — it installs the protocol the extension speaks. If it
is missing, the extension tells you exactly that rather than failing obscurely.

Nothing is sent anywhere except to the agent you are running. The extension
starts it as a child process, talks to it over stdio, and stops it when the
window closes.

## Commands

| Command | Shortcut | What it does |
|---|---|---|
| `Elidia: Open Chat` | `Ctrl+Alt+E` / `Cmd+Alt+E` | Opens the chat panel |
| `Elidia: Explain Selection` | right-click | Explains the selected code |
| `Elidia: Fix Selection` | right-click | Finds and fixes a problem in it |
| `Elidia: Select Model` | — | Switches the model |
| `Elidia: Cancel Current Turn` | — | Stops what the agent is doing |
| `Elidia: Restart Agent` | — | Restarts the agent process |
| `Elidia: Show Log` | — | Opens the Elidia output channel |

## Settings

| Setting | Default | Purpose |
|---|---|---|
| `elidia.acpPath` | `""` | Path to `elidia-acp`. Empty searches your PATH, then a Python that can run `python -m acp_adapter`. |

The extension verifies a candidate actually starts before using it, so a stale
`elidia` from an older install will not be picked up silently.

## How it connects

```
VS Code  ──stdio JSON-RPC (ACP)──▶  elidia-acp  ──▶  Elidia agent
```

It speaks the [Agent Client Protocol](https://agentclientprotocol.com), the same
interface Elidia exposes to other ACP-capable editors — so the agent behaves the
same wherever you use it.

## Troubleshooting

**"No Elidia agent found"** — install it: `pip install "elidia-agent-cli[acp]"`,
or point `elidia.acpPath` at the executable.

**"Elidia is installed but the ACP extra is missing"** — you have the CLI without
the protocol package. The same install command adds it.

**Anything else** — run `Elidia: Show Log`. The agent's own output goes there.

## Licence

MIT — Elidia Technology Pvt Ltd.
