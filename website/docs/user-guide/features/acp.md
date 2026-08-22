---
sidebar_position: 11
title: "ACP Editor Integration"
description: "Use Elidia Agent inside ACP-compatible editors such as VS Code, Zed, and JetBrains"
---

# ACP Editor Integration

Elidia Agent can run as an ACP server, letting ACP-compatible editors talk to Elidia over stdio and render:

- chat messages
- tool activity
- file diffs
- terminal commands
- approval prompts
- streamed thinking / response chunks

ACP is a good fit when you want Elidia to behave like an editor-native coding agent instead of a standalone CLI or messaging bot.

## What Elidia exposes in ACP mode

Elidia runs with a curated `elidia-acp` toolset designed for editor workflows. It includes:

- file tools: `read_file`, `write_file`, `patch`, `search_files`
- terminal tools: `terminal`, `process`
- web/browser tools
- memory, todo, session search
- skills
- execute_code and delegate_task
- vision

It intentionally excludes things that do not fit typical editor UX, such as messaging delivery and cronjob management.

## Installation

Install Elidia normally, then add the ACP extra:

```bash
pip install -e '.[acp]'
```

This installs the `agent-client-protocol` dependency and enables:

- `elidia acp`
- `elidia-acp`
- `python -m acp_adapter`

For Zed registry installs, Zed launches Elidia through the official ACP Registry entry. That entry uses a `uvx` distribution that runs:

```bash
uvx --from 'elidia-agent[acp]==<version>' elidia-acp
```

Make sure `uv` is available on `PATH` before using the registry install path.

## Launching the ACP server

Any of the following starts Elidia in ACP mode:

```bash
elidia acp
```

```bash
elidia-acp
```

```bash
python -m acp_adapter
```

Elidia logs to stderr so stdout remains reserved for ACP JSON-RPC traffic.

For non-interactive checks:

```bash
elidia acp --version
elidia acp --check
```

### Browser tools (optional)

Browser tools (`browser_navigate`, `browser_click`, etc.) depend on the
`agent-browser` npm package and Chromium, which aren't part of the Python
wheel. Install them with:

```bash
elidia acp --setup-browser           # interactive (prompts before ~400 MB download)
elidia acp --setup-browser --yes     # accept the download non-interactively
```

This is the standalone command. The Zed registry's terminal-auth flow (`elidia acp --setup`) also offers the browser bootstrap as a follow-up question after model selection, so most users never need to run `--setup-browser` directly.

What it does:

- Installs Node.js 22 LTS into `~/.elidia/node/` if missing
- `npm install -g agent-browser @askjo/camofox-browser` into that prefix (no sudo needed — `npm`'s `--prefix` points at the user-writable Elidia-managed Node)
- Installs Playwright Chromium, or uses a detected system Chrome/Chromium when available

The bootstrap is idempotent — re-running it is fast and skips work that's already done.

## Editor setup

### VS Code

Install the [ACP Client](https://marketplace.visualstudio.com/items?itemName=formulahendry.acp-client) extension.

To connect:

1. Open the ACP Client panel from the Activity Bar.
2. Select **Elidia Agent** from the built-in agent list.
3. Connect and start chatting.

If you want to define Elidia manually, add it through VS Code settings under `acp.agents`:

```json
{
  "acp.agents": {
    "Elidia Agent": {
      "command": "elidia",
      "args": ["acp"]
    }
  }
}
```

### Zed

Zed v0.221.x and newer installs external agents through the official ACP Registry.

1. Open the Agent Panel.
2. Click **Add Agent**, or run the `zed: acp registry` command.
3. Search for **Elidia Agent**.
4. Install it and start a new Elidia external-agent thread.

Prerequisites:

- Configure Elidia provider credentials first with `elidia model`, or set them in `~/.elidia/.env` / `~/.elidia/config.yaml`.
- Install `uv` so the registry launcher can run `uvx --from 'elidia-agent[acp]==<version>' elidia-acp`.

For local development before the registry entry is available, use a custom agent server in Zed settings:

```json
{
  "agent_servers": {
    "elidia-agent": {
      "type": "custom",
      "command": "elidia",
      "args": ["acp"]
    }
  }
}
```

### JetBrains

Use an ACP-compatible plugin and point it at:

```text
/path/to/elidia-agent/acp_registry
```

## Registry manifest

The source copy of Elidia' official ACP Registry metadata lives at:

```text
acp_registry/agent.json
acp_registry/icon.svg
```

The upstream registry PR copies those files into the top-level `elidia-agent/` directory in `agentclientprotocol/registry`.

The registry entry uses a `uvx` distribution that points directly at the `elidia-agent` PyPI release:

```text
uvx --from 'elidia-agent[acp]==<version>' elidia-acp
```

The registry CI verifies that the pinned version exists on PyPI, so the manifest's `version` and uvx `package` pin must always match `pyproject.toml`. `scripts/release.py` keeps them in lockstep automatically.

## Configuration and credentials

ACP mode uses the same Elidia configuration as the CLI:

- `~/.elidia/.env`
- `~/.elidia/config.yaml`
- `~/.elidia/skills/`
- `~/.elidia/state.db`

Provider resolution uses Elidia' normal runtime resolver, so ACP inherits the currently configured provider and credentials. Elidia also advertises a terminal auth method (`--setup`) for first-run registry clients; this opens Elidia' interactive model/provider setup.

## Session behavior

ACP sessions are tracked by the ACP adapter's in-memory session manager while the server is running.

Each session stores:

- session ID
- working directory
- selected model
- current conversation history
- cancel event

The underlying `AIAgent` still uses Elidia' normal persistence/logging paths, but ACP `list/load/resume/fork` are scoped to the currently running ACP server process.

## Working directory behavior

ACP sessions bind the editor's cwd to the Elidia task ID so file and terminal tools run relative to the editor workspace, not the server process cwd.

## Approvals

Dangerous terminal commands can be routed back to the editor as approval prompts. ACP approval options are simpler than the CLI flow:

- allow once
- allow always
- deny

On timeout or error, the approval bridge denies the request.

### Session-scoped edit auto-approval

ACP exposes a third tier between *allow once* and *allow always*: **Allow for session**. Picking it from the editor's permission prompt records the approval inside the current ACP session only — every subsequent matching command in that session goes through without prompting, but a new ACP session (or restarting the editor) resets the slate and re-prompts the first time.

| Option | Editor label | Scope | Persisted across restarts |
|---|---|---|---|
| `allow_once` | Allow once | This one tool call | No |
| `allow_session` | Allow for session | All matching calls in this ACP session | No — cleared when the session ends |
| `allow_always` | Allow always | All future sessions | Yes (written to the Elidia permanent allowlist) |
| `deny` | Deny | This one tool call | No |

`allow_session` is the right default for an editor workflow where you trust an agent for the duration of a task but don't want to grant a long-lived allowlist entry. The safety trade-off is straightforward: the broader the scope, the less the editor will interrupt you, and the more damage a misbehaving agent (or prompt injection) can do before you notice. Start with `allow_once` for unfamiliar commands; promote to `allow_session` once you've seen the agent run the same pattern correctly a few times; reserve `allow_always` for truly idempotent commands you trust forever (e.g. `git status`).

The ACP bridge maps these options onto Elidia' internal approval semantics — `allow_always` writes a permanent allowlist entry the same way the CLI does, while `allow_session` only affects the in-process approval cache for the current ACP session.

## Troubleshooting

### ACP agent does not appear in the editor

Check:

- In Zed, open the ACP Registry with `zed: acp registry` and search for **Elidia Agent**.
- For manual/local development, verify the custom `agent_servers` command points to `elidia acp`.
- Elidia is installed and on your PATH.
- The ACP extra is installed (`pip install -e '.[acp]'`).
- `uv` is installed if launching from the official Zed registry entry.

### ACP starts but immediately errors

Try these checks:

```bash
elidia acp --version
elidia acp --check
elidia doctor
elidia status
```

### Missing credentials

ACP mode uses Elidia' existing provider setup. Configure credentials with:

```bash
elidia model
```

or by editing `~/.elidia/.env`. Registry clients can also trigger Elidia' terminal auth flow, which runs the same interactive provider/model setup.

### Zed registry launcher cannot find uv

Install `uv` from the official uv installation docs, then retry the Elidia Agent thread from Zed.

## See also

- [ACP Internals](../../developer-guide/acp-internals.md)
- [Provider Runtime Resolution](../../developer-guide/provider-runtime.md)
- [Tools Runtime](../../developer-guide/tools-runtime.md)
