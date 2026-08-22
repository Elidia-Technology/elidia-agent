
# CLI Commands Reference

This page covers the **terminal commands** you run from your shell.

For in-chat slash commands, see [Slash Commands Reference](https://aiutils.io/elidia/reference/slash-commands).

## Global entrypoint

```bash
elidia [global-options] <command> [subcommand/options]
```

### Global options

| Option | Description |
|--------|-------------|
| `--version`, `-V` | Show version and exit. |
| `--profile <name>`, `-p <name>` | Select which Elidia profile to use for this invocation. Overrides the sticky default set by `elidia profile use`. |
| `--resume <session>`, `-r <session>` | Resume a previous session by ID or title. |
| `--continue [name]`, `-c [name]` | Resume the most recent session, or the most recent session matching a title. |
| `--worktree`, `-w` | Start in an isolated git worktree for parallel-agent workflows. |
| `--yolo` | Bypass dangerous-command approval prompts. |
| `--pass-session-id` | Include the session ID in the agent's system prompt. |
| `--ignore-user-config` | Ignore `~/.elidia/config.yaml` and fall back to built-in defaults. Credentials in `.env` are still loaded. |
| `--ignore-rules` | Skip auto-injection of `AGENTS.md`, `SOUL.md`, `.cursorrules`, memory, and preloaded skills. |
| `--tui` | Launch the [TUI](https://aiutils.io/elidia/user-guide/tui) instead of the classic CLI. Equivalent to `ELIDIA_TUI=1`. Always wins over `display.interface`. |
| `--cli` | Force the classic prompt_toolkit REPL. Use this to override `display.interface: tui` for a single invocation. |
| `--dev` | With `--tui`: run the TypeScript sources directly via `tsx` instead of the prebuilt bundle (for TUI contributors). |

## Top-level commands

| Command | Purpose |
|---------|---------|
| `elidia chat` | Interactive or one-shot chat with the agent. |
| `elidia model` | Interactively choose the default provider and model. |
| `elidia fallback` | Manage fallback providers tried when the primary model errors. |
| `elidia gateway` | Run or manage the messaging gateway service. |
| `elidia proxy` | Local OpenAI-compatible proxy that attaches OAuth provider credentials. See [Subscription Proxy](https://aiutils.io/elidia/user-guide/features/subscription-proxy). |
| `elidia lsp` | Manage Language Server Protocol integration (semantic diagnostics for write_file/patch). |
| `elidia setup` | Interactive setup wizard for all or part of the configuration. |
| `elidia whatsapp` | Configure and pair the WhatsApp bridge. |
| `elidia slack` | Slack helpers (currently: generate the app manifest with every command as a native slash). |
| `elidia auth` | Manage credentials — add, list, remove, reset, set strategy. Handles OAuth flows for Codex/Elidia/Anthropic. |
| `elidia login` / `logout` | **Deprecated** — use `elidia auth` instead. |
| `elidia send` | Send a one-shot message to a configured messaging platform (Telegram, Discord, Slack, Signal, SMS, …). Useful from shell scripts, cron jobs, CI hooks, and monitoring daemons — no agent loop, no LLM. |
| `elidia secrets` | Manage external secret sources (currently Bitwarden Secrets Manager) for pulling API keys at process startup instead of from `~/.elidia/.env`. |
| `elidia migrate` | Diagnose and (optionally) rewrite `config.yaml` to replace references to retired models or deprecated settings (e.g. `migrate xai`). |
| `elidia status` | Show agent, auth, and platform status. |
| `elidia cron` | Inspect and tick the cron scheduler. |
| `elidia kanban` | Multi-profile collaboration board (tasks, links, dispatcher). |
| `elidia webhook` | Manage dynamic webhook subscriptions for event-driven activation. |
| `elidia hooks` | Inspect, approve, or remove shell-script hooks declared in `config.yaml`. |
| `elidia doctor` | Diagnose config and dependency issues. |
| `elidia security audit` | On-demand supply-chain audit (OSV.dev) for the venv, plugin requirements, and pinned MCP servers. |
| `elidia dump` | Copy-pasteable setup summary for support/debugging. |
| `elidia prompt-size` | Show a byte breakdown of the system prompt + tool schemas (skills index, memory, profile). Runs offline. |
| `elidia debug` | Debug tools — upload logs and system info for support. |
| `elidia backup` | Back up Elidia home directory to a zip file. |
| `elidia checkpoints` | Inspect / prune / clear `~/.elidia/checkpoints/` (the shadow store used by `/rollback`). Run with no args for a status overview. |
| `elidia import` | Restore an Elidia backup from a zip file. |
| `elidia logs` | View, tail, and filter agent/gateway/error log files. |
| `elidia config` | Show, edit, migrate, and query configuration files. |
| `elidia pairing` | Approve or revoke messaging pairing codes. |
| `elidia skills` | Browse, install, publish, audit, and configure skills. |
| `elidia bundles` | Group several skills under a single `/<name>` slash command. See [Skill Bundles](skills.md). |
| `elidia curator` | Background skill maintenance — status, run, pause, pin. See [Curator](https://aiutils.io/elidia/user-guide/features/curator). |
| `elidia memory` | Configure external memory provider. Plugin-specific subcommands (e.g. `elidia honcho`) register automatically when their provider is active. |
| `elidia acp` | Run Elidia as an ACP server for editor integration. |
| `elidia mcp` | Manage MCP server configurations and run Elidia as an MCP server. |
| `elidia plugins` | Manage Elidia Agent plugins (install, enable, disable, remove). |
| `elidia portal` | Elidia Portal status, subscription link, and Tool Gateway routing. See [Tool Gateway](tool-gateway.md). |
| `elidia tools` | Configure enabled tools per platform. |
| `elidia computer-use` | Install or check the cua-driver backend (macOS Computer Use). |
| `elidia sessions` | Browse, export, prune, rename, and delete sessions. |
| `elidia insights` | Show token/cost/activity analytics. |
| `elidia claw` | OpenClaw migration helpers. |
| `elidia dashboard` | Launch the web dashboard for managing config, API keys, and sessions. |
| `elidia profile` | Manage profiles — multiple isolated Elidia instances. |
| `elidia completion` | Print shell completion scripts (bash/zsh/fish). |
| `elidia version` | Show version information. |
| `elidia update` | Pull latest code and reinstall dependencies (git installs), or check PyPI and `pip install --upgrade` (pip installs). `--check` previews without installing; `--backup` takes a pre-pull `ELIDIA_HOME` snapshot. |
| `elidia uninstall` | Remove Elidia from the system. |

## `elidia chat`

```bash
elidia chat [options]
```

Common options:

| Option | Description |
|--------|-------------|
| `-q`, `--query "..."` | One-shot, non-interactive prompt. |
| `-m`, `--model <model>` | Override the model for this run. |
| `-t`, `--toolsets <csv>` | Enable a comma-separated set of toolsets. |
| `--provider <provider>` | Force a provider: `auto`, `openrouter`, `elidia`, `openai-codex`, `copilot-acp`, `copilot`, `anthropic`, `gemini`, `google-gemini-cli`, `huggingface`, `novita`, `zai`, `kimi-coding`, `kimi-coding-cn`, `minimax`, `minimax-cn`, `minimax-oauth`, `kilocode`, `xiaomi`, `arcee`, `gmi`, `alibaba`, `alibaba-coding-plan` (alias `alibaba_coding`), `deepseek`, `nvidia`, `ollama-cloud`, `xai` (alias `grok`), `xai-oauth` (alias `grok-oauth`), `qwen-oauth`, `bedrock`, `opencode-zen`, `opencode-go`, `azure-foundry`, `lmstudio`, `stepfun`, `tencent-tokenhub` (alias `tencent`, `tokenhub`). |
| `-s`, `--skills <name>` | Preload one or more skills for the session (can be repeated or comma-separated). |
| `-v`, `--verbose` | Verbose output. |
| `-Q`, `--quiet` | Programmatic mode: suppress banner/spinner/tool previews. |
| `--image <path>` | Attach a local image to a single query. |
| `--resume <session>` / `--continue [name]` | Resume a session directly from `chat`. |
| `--worktree` | Create an isolated git worktree for this run. |
| `--checkpoints` | Enable filesystem checkpoints before destructive file changes. |
| `--yolo` | Skip approval prompts. |
| `--pass-session-id` | Pass the session ID into the system prompt. |
| `--ignore-user-config` | Ignore `~/.elidia/config.yaml` and use built-in defaults. Credentials in `.env` are still loaded. Useful for isolated CI runs, reproducible bug reports, and third-party integrations. |
| `--ignore-rules` | Skip auto-injection of `AGENTS.md`, `SOUL.md`, `.cursorrules`, persistent memory, and preloaded skills. Combine with `--ignore-user-config` for a fully isolated run. |
| `--source <tag>` | Session source tag for filtering (default: `cli`). Use `tool` for third-party integrations that should not appear in user session lists. |
| `--max-turns <N>` | Maximum tool-calling iterations per conversation turn (default: 90, or `agent.max_turns` in config). |

Examples:

```bash
elidia
elidia chat -q "Summarize the latest PRs"
elidia chat --provider openrouter --model anthropic/claude-sonnet-4.6
elidia chat --toolsets web,terminal,skills
elidia chat --quiet -q "Return only JSON"
elidia chat --worktree -q "Review this repo and open a PR"
elidia chat --ignore-user-config --ignore-rules -q "Repro without my personal setup"
```

### `elidia -z <prompt>` — scripted one-shot

For programmatic callers (shell scripts, CI, cron, parent processes piping in a prompt), `elidia -z` is the purest one-shot entry point: **single prompt in, final response text out, nothing else on stdout or stderr.** No banner, no spinner, no tool previews, no `Session:` line — just the agent's final reply as plain text.

```bash
elidia -z "What's the capital of France?"
# → Paris.

# Parent scripts can cleanly capture the response:
answer=$(elidia -z "summarize this" < /path/to/file.txt)
```

Per-run overrides (no mutation to `~/.elidia/config.yaml`):

| Flag | Equivalent env var | Purpose |
|---|---|---|
| `-m` / `--model <model>` | `ELIDIA_INFERENCE_MODEL` | Override the model for this run |
| `--provider <provider>` | _(none)_ | Override the provider for this run |

```bash
elidia -z "…" --provider openrouter --model openai/gpt-5.5
# or:
ELIDIA_INFERENCE_MODEL=anthropic/claude-sonnet-4.6 elidia -z "…"
```

Same agent, same tools, same skills — just strips every interactive / cosmetic layer. If you need tool output in the transcript too, use `elidia chat -q` instead; `-z` is explicitly for "I only want the final answer".

## `elidia model`

Interactive provider + model selector. **This is the command for adding new providers, setting up API keys, and running OAuth flows.** Run it from your terminal — not from inside an active Elidia chat session.

```bash
elidia model
```

Use this when you want to:
- **add a new provider** (OpenRouter, Anthropic, Copilot, DeepSeek, custom, etc.)
- log into OAuth-backed providers (Anthropic, Copilot, Codex, Elidia Portal)
- enter or update API keys
- pick from provider-specific model lists
- configure a custom/self-hosted endpoint
- save the new default into config

> [!WARNING] elidia model vs /model — know the difference
> **`elidia model`** (run from your terminal, outside any Elidia session) is the **full provider setup wizard**. It can add new providers, run OAuth flows, prompt for API keys, and configure endpoints.
>
> **`/model`** (typed inside an active Elidia chat session) can only **switch between providers and models you've already set up**. It cannot add new providers, run OAuth, or prompt for API keys.
>
> **If you need to add a new provider:** Exit your Elidia session first (`Ctrl+C` or `/quit`), then run `elidia model` from your terminal prompt.


### `/model` slash command (mid-session)

Switch between already-configured models without leaving a session:

```
/model                              # Show current model and available options
/model claude-sonnet-4              # Switch model (auto-detects provider)
/model zai:glm-5                    # Switch provider and model
/model custom:qwen-2.5              # Use model on your custom endpoint
/model custom                       # Auto-detect model from custom endpoint
/model custom:local:qwen-2.5        # Use a named custom provider
/model openrouter:anthropic/claude-sonnet-4  # Switch back to cloud
```

By default, `/model` changes apply **to the current session only**. Add `--global` to persist the change to `config.yaml`:

```
/model claude-sonnet-4 --global     # Switch and save as new default
```

> [!NOTE] What if I only see OpenRouter models?
> If you've only configured OpenRouter, `/model` will only show OpenRouter models. To add another provider (Anthropic, DeepSeek, Copilot, etc.), exit your session and run `elidia model` from the terminal.


Provider and base URL changes are persisted to `config.yaml` automatically. When switching away from a custom endpoint, the stale base URL is cleared to prevent it leaking into other providers.

## `elidia gateway`

```bash
elidia gateway <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `run` | Run the gateway in the foreground. Recommended for WSL, Docker, and Termux. |
| `start` | Start the installed systemd/launchd background service. |
| `stop` | Stop the service (or foreground process). |
| `restart` | Restart the service. |
| `status` | Show service status. |
| `list` | List **all profiles** and whether each profile's gateway is currently running (with PID where available). Handy when you run multiple profiles side-by-side and want a single overview. |
| `install` | Install as a systemd (Linux) or launchd (macOS) background service. |
| `uninstall` | Remove the installed service. |
| `setup` | Interactive messaging-platform setup. |

Options:

| Option | Description |
|--------|-------------|
| `--all` | On `start` / `restart` / `stop`: act on **every profile's** gateway, not just the active `ELIDIA_HOME`. Useful if you run multiple profiles side-by-side and want to restart them all after `elidia update`. |
| `--no-supervise` | On `run`: inside the s6-overlay Docker image, opt out of auto-supervision and use pre-s6 foreground semantics — gateway runs as the container's main process with no auto-restart. No-op outside the s6 image. Equivalent to setting `ELIDIA_GATEWAY_NO_SUPERVISE=1`. |

> [!TIP] WSL users
> Use `elidia gateway run` instead of `elidia gateway start` — WSL's systemd support is unreliable. Wrap it in tmux for persistence: `tmux new -s elidia 'elidia gateway run'`. See [WSL FAQ](https://aiutils.io/elidia/reference/faq) for details.


## `elidia lsp`

```bash
elidia lsp <subcommand>
```

Manage the Language Server Protocol integration. LSP runs real
language servers (pyright, gopls, rust-analyzer, …) in the
background and feeds their diagnostics into the post-write check
used by `write_file` and `patch`. Gated on git workspace detection
— LSP only runs when the cwd or edited file is inside a git
worktree.

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `status` | Show service state, configured servers, install status. |
| `list` | Print the registry of supported servers. Pass `--installed-only` to skip missing ones. |
| `install <id>` | Eagerly install one server's binary. |
| `install-all` | Install every server with a known auto-install recipe. |
| `restart` | Tear down running clients so the next edit re-spawns. |
| `which <id>` | Print the resolved binary path for one server. |

See [LSP — Semantic Diagnostics](https://aiutils.io/elidia/user-guide/features/lsp) for
the full guide, supported languages, and configuration knobs.

## `elidia setup`

```bash
elidia setup [model|tts|terminal|gateway|tools|agent] [--non-interactive] [--reset] [--quick] [--reconfigure] [--portal]
```

**Easiest path:** `elidia setup --portal` — OAuth into Elidia Portal and opt into the [Tool Gateway](tool-gateway.md) in one shot.

**First run:** launches the first-time wizard.

**Returning user (already configured):** drops straight into the full reconfigure wizard — every prompt shows your current value as its default, press Enter to keep or type a new value. No menu.

Jump into one section instead of the full wizard:

| Section | Description |
|---------|-------------|
| `model` | Provider and model setup. |
| `terminal` | Terminal backend and sandbox setup. |
| `gateway` | Messaging platform setup. |
| `tools` | Enable/disable tools per platform. |
| `agent` | Agent behavior settings. |

Options:

| Option | Description |
|--------|-------------|
| `--quick` | On returning-user runs: only prompt for items that are missing or unset. Skip items you already have configured. |
| `--non-interactive` | Use defaults / environment values without prompts. |
| `--reset` | Reset configuration to defaults before setup. |
| `--reconfigure` | Backwards-compat alias — bare `elidia setup` on an existing install now does this by default. |
| `--portal` | One-shot Elidia Portal setup: log in via OAuth, set Elidia as the inference provider, and opt into the [Tool Gateway](tool-gateway.md). Skips the rest of the wizard. |

## `elidia portal`

```bash
elidia portal [status|open|tools]
```

Inspect Elidia Portal auth, Tool Gateway routing, and reach the subscription page. Subcommand-less invocation runs `status`.

| Subcommand | Description |
|------------|-------------|
| `status` (default) | Portal auth state + per-tool Tool Gateway routing summary. Also shown when no subcommand is given. |
| `open` | Open `developer.aiutils.io/manage-subscription` in your default browser. |
| `tools` | List every Tool Gateway partner (Firecrawl, FAL, OpenAI TTS, Browser Use, Modal) and which are routed via Elidia. |

For configuration of the gateway itself, see [Tool Gateway](tool-gateway.md). For the one-shot setup path, see `elidia setup --portal` above.

## `elidia whatsapp`

```bash
elidia whatsapp
```

Runs the WhatsApp pairing/setup flow, including mode selection and QR-code pairing.

## `elidia slack`

```bash
elidia slack manifest              # print manifest to stdout
elidia slack manifest --write      # write to ~/.elidia/slack-manifest.json
elidia slack manifest --slashes-only  # just the features.slash_commands array
```

Generates a Slack app manifest that registers every gateway command in
`COMMAND_REGISTRY` (`/btw`, `/stop`, `/model`, …) as a first-class
Slack slash command — matching Discord and Telegram parity. Paste the
output into your Slack app config at
[https://api.slack.com/apps](https://api.slack.com/apps) → your app →
**Features → App Manifest → Edit**, then **Save**. Slack prompts for
reinstall if scopes or slash commands changed.

| Flag | Default | Purpose |
|------|---------|---------|
| `--write [PATH]` | stdout | Write to a file instead of stdout. Bare `--write` writes `$ELIDIA_HOME/slack-manifest.json`. |
| `--name NAME` | `Elidia` | Bot display name in Slack. |
| `--description DESC` | default blurb | Bot description shown in the Slack app directory. |
| `--slashes-only` | off | Emit only `features.slash_commands` for merging into a manually-maintained manifest. |

Run `elidia slack manifest --write` again after `elidia update` to pick
up any new commands.


## `elidia send`

```bash
elidia send --to <target> "message text"
elidia send --to <target> --file <path>
echo "message" | elidia send --to <target>
elidia send --list [platform]
```

Send a one-shot message to a configured messaging platform without spinning up an agent or gateway loop. Reuses the gateway's already-configured credentials (`~/.elidia/.env` + `~/.elidia/config.yaml`) so ops scripts, cron jobs, CI hooks, and monitoring daemons can post status updates without reimplementing each platform's REST client.

For bot-token platforms (Telegram, Discord, Slack, Signal, SMS, WhatsApp-CloudAPI) no running gateway is required — `elidia send` talks directly to the platform's REST endpoint. Plugin platforms that need a persistent adapter still require a live gateway.

| Option | Description |
|--------|-------------|
| `-t`, `--to <TARGET>` | Delivery target. Formats: `platform` (uses home channel), `platform:chat_id`, `platform:chat_id:thread_id`, or `platform:#channel-name`. Examples: `telegram`, `telegram:-1001234567890`, `discord:#ops`, `slack:C0123ABCD`, `signal:+15551234567`. |
| `-f`, `--file <PATH>` | Read the message body from `PATH`. Pass `-` to force reading from stdin. |
| `-s`, `--subject <LINE>` | Prepend a subject/header line before the message body. |
| `-l`, `--list [platform]` | List configured targets across all platforms (or only the given platform). |
| `-q`, `--quiet` | Suppress stdout on success — useful in scripts (rely on exit code only). |
| `--json` | Emit raw JSON result instead of human-readable output. |

If neither a positional `message` argument nor `--file` is provided, `elidia send` reads from stdin when it is not a TTY. Exit codes: `0` on success, `1` on delivery/backend failure, `2` on usage errors.

Examples:

```bash
elidia send --to telegram "deploy finished"
echo "RAM 92%" | elidia send --to telegram:-1001234567890
elidia send --to discord:#ops --file /tmp/report.md
elidia send --to slack:#eng --subject "[CI]" --file build.log
elidia send --list                  # all platforms
elidia send --list telegram         # filter by platform
```


## `elidia secrets`

```bash
elidia secrets bitwarden <subcommand>
elidia secrets bw <subcommand>          # short alias
```

Pull API keys from an external secret manager at process startup instead of storing them in `~/.elidia/.env`. Currently supports **Bitwarden Secrets Manager**. See the full guide: [Bitwarden integration](https://aiutils.io/elidia/user-guide/secrets/bitwarden).

`bitwarden` (alias `bw`) subcommands:

| Subcommand | Description |
|------------|-------------|
| `setup` | Interactive wizard: install the pinned `bws` binary, store an access token, and pick a project. Accepts `--project-id`, `--access-token`, and `--server-url` for non-interactive use. |
| `status` | Show current config, binary path/version, and last fetch info. |
| `sync` | Fetch secrets now and report what changed. Add `--apply` to actually export the secrets into the current shell's environment (default is dry-run). |
| `install` | Download and verify the pinned `bws` binary. `--force` re-downloads even if a managed copy already exists. |
| `disable` | Turn off the Bitwarden integration. |


## `elidia migrate`

```bash
elidia migrate <type>
```

Diagnose and (optionally) rewrite the active `config.yaml` to replace references to retired models or deprecated settings. A timestamped backup of the original `config.yaml` is taken before any rewrite (skip with `--no-backup`).

| Subcommand | Description |
|------------|-------------|
| `xai` | Scan `config.yaml` for references to xAI models scheduled for retirement on May 15, 2026 and (with `--apply`) rewrite them in-place to the official replacements per the xAI migration guide. Defaults to dry-run. |

Common flags for migration subcommands:

| Flag | Description |
|------|-------------|
| `--apply` | Rewrite `config.yaml` in-place (default: dry-run, no writes). |
| `--no-backup` | Skip the timestamped backup of `config.yaml` when applying. |

> Not to be confused with `elidia claw migrate` (one-shot import of OpenClaw configuration into Elidia) — `elidia migrate` is the top-level config-rewrite command.


## `elidia proxy`

```bash
elidia proxy <subcommand>
```

Run a local OpenAI-compatible HTTP server that forwards requests to an OAuth-authenticated upstream provider (e.g. Elidia Portal, xAI). External apps can point at the proxy with any bearer token; the proxy attaches your real OAuth credentials on the way out. See [Subscription Proxy](https://aiutils.io/elidia/user-guide/features/subscription-proxy) for the full guide.

| Subcommand | Description |
|------------|-------------|
| `start` | Run the proxy in the foreground. Flags: `--provider <elidia\|xai>` (default `elidia`), `--host <addr>` (default `127.0.0.1`; use `0.0.0.0` to expose on LAN), `--port <int>` (default `8645`). |
| `status` | Show which proxy upstreams are ready (credentials present, OAuth valid). |
| `providers` | List available proxy upstream providers. |


## `elidia security`

```bash
elidia security <subcommand>
```

On-demand vulnerability scan against [OSV.dev](https://osv.dev). Covers the Elidia venv (installed PyPI distributions), Python dependencies declared by plugins under `~/.elidia/plugins/`, and pinned `npx`/`uvx` MCP servers in `config.yaml`. Does NOT scan globally-installed packages or editor/browser extensions.

| Subcommand | Description |
|------------|-------------|
| `audit` | Run a one-shot supply-chain audit. |

`audit` flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | off | Emit machine-readable JSON instead of human-readable text. |
| `--fail-on <level>` | `critical` | Exit non-zero when any finding meets this severity (`low`, `moderate`, `high`, `critical`). |
| `--skip-venv` | off | Skip scanning the Elidia Python venv. |
| `--skip-plugins` | off | Skip scanning plugin requirements files. |
| `--skip-mcp` | off | Skip scanning pinned MCP servers in `config.yaml`. |


## `elidia login` / `elidia logout` *(Deprecated)*

> [!WARNING]
> `elidia login` has been removed. Use `elidia auth` to manage OAuth credentials, `elidia model` to select a provider, or `elidia setup` for full interactive setup.


## `elidia auth`

Manage credential pools for same-provider key rotation. See [Credential Pools](https://aiutils.io/elidia/user-guide/features/credential-pools) for full documentation.

```bash
elidia auth                                              # Interactive wizard
elidia auth list                                         # Show all pools
elidia auth list openrouter                              # Show specific provider
elidia auth add openrouter --api-key sk-or-v1-xxx        # Add API key
elidia auth add anthropic --type oauth                   # Add OAuth credential
elidia auth remove openrouter 2                          # Remove by index
elidia auth reset openrouter                             # Clear cooldowns
elidia auth status anthropic                             # Show auth status for a provider
elidia auth logout anthropic                             # Log out and clear stored auth state
elidia auth spotify                                      # Authenticate Elidia with Spotify via PKCE
```

Subcommands: `add`, `list`, `remove`, `reset`, `status`, `logout`, `spotify`. When called with no subcommand, launches the interactive management wizard.

## `elidia status`

```bash
elidia status [--all] [--deep]
```

| Option | Description |
|--------|-------------|
| `--all` | Show all details in a shareable redacted format. |
| `--deep` | Run deeper checks that may take longer. |

## `elidia cron`

```bash
elidia cron <list|create|edit|pause|resume|run|remove|status|tick>
```

| Subcommand | Description |
|------------|-------------|
| `list` | Show scheduled jobs. |
| `create` / `add` | Create a scheduled job from a prompt, optionally attaching one or more skills via repeated `--skill`. |
| `edit` | Update a job's schedule, prompt, name, delivery, repeat count, or attached skills. Supports `--clear-skills`, `--add-skill`, and `--remove-skill`. |
| `pause` | Pause a job without deleting it. |
| `resume` | Resume a paused job and compute its next future run. |
| `run` | Trigger a job on the next scheduler tick. |
| `remove` | Delete a scheduled job. |
| `status` | Check whether the cron scheduler is running. |
| `tick` | Run due jobs once and exit. |

## `elidia kanban`

```bash
elidia kanban [--board <slug>] <action> [options]
```

Multi-profile, multi-project collaboration board. Each install can host many boards (one per project, repo, or domain); each board is a standalone queue with its own SQLite DB and dispatcher scope. New installs start with one board called `default`, whose DB is `~/.elidia/kanban.db` for back-compat; additional boards live at `~/.elidia/kanban/boards/<slug>/kanban.db`. The gateway-embedded dispatcher sweeps every board per tick.

**Global flags (apply to every action below):**

| Flag | Purpose |
|------|---------|
| `--board <slug>` | Operate on a specific board. Defaults to the current board (set via `elidia kanban boards switch`, the `ELIDIA_KANBAN_BOARD` env var, or `default`). |

**This is the human / scripting surface.** Agent workers spawned by the dispatcher drive the board through a dedicated `kanban_*` [toolset](https://aiutils.io/elidia/user-guide/features/kanban) (`kanban_show`, `kanban_complete`, `kanban_block`, `kanban_create`, `kanban_link`, `kanban_comment`, `kanban_heartbeat`; orchestrator profiles also get `kanban_list` and `kanban_unblock`) instead of shelling to `elidia kanban`. Workers have `ELIDIA_KANBAN_BOARD` pinned in their env so they physically cannot see other boards.

| Action | Purpose |
|--------|---------|
| `init` | Create `kanban.db` if missing. Idempotent. |
| `boards list` / `boards ls` | List all boards with task counts. `--json`, `--all` (include archived). |
| `boards create <slug>` | Create a new board. Flags: `--name`, `--description`, `--icon`, `--color`, `--switch` (make active). Slug is kebab-case, auto-downcased. |
| `boards switch <slug>` / `boards use` | Persist `<slug>` as the active board (writes `~/.elidia/kanban/current`). |
| `boards show` / `boards current` | Print the currently-active board's name, DB path, and task counts. |
| `boards rename <slug> "<name>"` | Change a board's display name. Slug is immutable. |
| `boards rm <slug>` | Archive (default) or hard-delete a board. `--delete` skips the archive step. Archived boards move to `boards/_archived/<slug>-<ts>/`. Refused for `default`. |
| `create "<title>"` | Create a new task on the active board. Flags: `--body`, `--assignee`, `--parent` (repeatable), `--workspace scratch\|worktree\|dir:<path>`, `--tenant`, `--priority`, `--triage`, `--idempotency-key`, `--max-runtime`, `--max-retries`, `--skill` (repeatable). |
| `list` / `ls` | List tasks on the active board. Filter with `--mine`, `--assignee`, `--status`, `--tenant`, `--archived`, `--json`. |
| `show <id>` | Show a task with comments and events. `--json` for machine output. |
| `assign <id> <profile>` | Assign or reassign. Use `none` to unassign. Refused while task is running. |
| `link <parent> <child>` | Add a dependency. Cycle-detected. Both tasks must be on the same board. |
| `unlink <parent> <child>` | Remove a dependency. |
| `claim <id>` | Atomically claim a ready task. Prints resolved workspace path. |
| `comment <id> "<text>"` | Append a comment. The next worker that claims the task reads it as part of its `kanban_show()` response. |
| `complete <id>` | Mark task done. Flags: `--result`, `--summary`, `--metadata`. |
| `block <id> "<reason>"` | Mark task blocked for human input. Also appends the reason as a comment. |
| `schedule <id> "<reason>"` | Park time-delay/follow-up work in `scheduled` so it is not shown as a human blocker. |
| `unblock <id>` | Return a blocked or scheduled task to ready (or `todo` if dependencies are still open). |
| `archive <id>` | Hide from default list. `gc` will remove scratch workspaces. |
| `tail <id>` | Follow a task's event stream. |
| `dispatch` | One dispatcher pass on the active board. Flags: `--dry-run`, `--max N`, `--failure-limit N`, `--json`. |
| `context <id>` | Print the full context a worker would see (title + body + parent results + comments). |
| `specify <id>` / `specify --all` | Flesh out a triage-column task into a concrete spec (title + body with goal, approach, acceptance criteria) via the auxiliary LLM, then promote it to `todo`. Flags: `--tenant` (scope `--all` to one tenant), `--author`, `--json`. Configure the model under `auxiliary.triage_specifier` in `config.yaml`. |
| `decompose <id>` / `decompose --all` | Fan a triage-column task out into a graph of child tasks routed to specialist profiles by description (the orchestrator-driven path). Falls back to specify-style single-task promotion when the LLM decides the task doesn't benefit from fan-out. Same flags as `specify`. Configure the model under `auxiliary.kanban_decomposer` in `config.yaml`. Also runs automatically every dispatcher tick when `kanban.auto_decompose: true` (the default). See [Auto vs Manual orchestration](https://aiutils.io/elidia/user-guide/features/kanban). |
| `gc` | Remove scratch workspaces for archived tasks. |

Examples:

```bash
# Create a second board and put a task on it without switching away.
elidia kanban boards create atm10-server --name "ATM10 Server" --icon 🎮
elidia kanban --board atm10-server create "Restart server" --assignee ops

# Switch the active board for subsequent calls.
elidia kanban boards switch atm10-server
elidia kanban list                  # shows atm10-server tasks

# Archive a board (recoverable) or hard-delete it.
elidia kanban boards rm atm10-server
elidia kanban boards rm atm10-server --delete
```

Board resolution order (highest precedence first): `--board <slug>` flag → `ELIDIA_KANBAN_BOARD` env var → `~/.elidia/kanban/current` file → `default`.

All actions are also available as a slash command in the gateway (`/kanban …`), with the same argument surface — including `boards` subcommands and the `--board` flag.

For the full design — comparison with Cline Kanban / Paperclip / NanoClaw / Gemini Enterprise, eight collaboration patterns, four user stories, concurrency correctness proof — see `docs/elidia-kanban-v1-spec.pdf` in the repository or the [Kanban user guide](https://aiutils.io/elidia/user-guide/features/kanban).

## `elidia webhook`

```bash
elidia webhook <subscribe|list|remove|test>
```

Manage dynamic webhook subscriptions for event-driven agent activation. Requires the webhook platform to be enabled in config — if not configured, prints setup instructions.

| Subcommand | Description |
|------------|-------------|
| `subscribe` / `add` | Create a webhook route. Returns the URL and HMAC secret to configure on your service. |
| `list` / `ls` | Show all agent-created subscriptions. |
| `remove` / `rm` | Delete a dynamic subscription. Static routes from config.yaml are not affected. |
| `test` | Send a test POST to verify a subscription is working. |

### `elidia webhook subscribe`

```bash
elidia webhook subscribe <name> [options]
```

| Option | Description |
|--------|-------------|
| `--prompt` | Prompt template with `{dot.notation}` payload references. |
| `--events` | Comma-separated event types to accept (e.g. `issues,pull_request`). Empty = all. |
| `--description` | Human-readable description. |
| `--skills` | Comma-separated skill names to load for the agent run. |
| `--deliver` | Delivery target: `log` (default), `telegram`, `discord`, `slack`, `github_comment`. |
| `--deliver-chat-id` | Target chat/channel ID for cross-platform delivery. |
| `--secret` | Custom HMAC secret. Auto-generated if omitted. |
| `--deliver-only` | Skip the agent — deliver the rendered `--prompt` as the literal message. Zero LLM cost, sub-second delivery. Requires `--deliver` to be a real target (not `log`). |

Subscriptions persist to `~/.elidia/webhook_subscriptions.json` and are hot-reloaded by the webhook adapter without a gateway restart.

## `elidia doctor`

```bash
elidia doctor [--fix]
```

| Option | Description |
|--------|-------------|
| `--fix` | Attempt automatic repairs where possible. |

## `elidia dump`

```bash
elidia dump [--show-keys]
```

Outputs a compact, plain-text summary of your entire Elidia setup. Designed to be copy-pasted into Discord, GitHub issues, or Telegram when asking for support — no ANSI colors, no special formatting, just data.

| Option | Description |
|--------|-------------|
| `--show-keys` | Show redacted API key prefixes (first and last 4 characters) instead of just `set`/`not set`. |

### What it includes

| Section | Details |
|---------|---------|
| **Header** | Elidia version, release date, git commit hash |
| **Environment** | OS, Python version, OpenAI SDK version |
| **Identity** | Active profile name, ELIDIA_HOME path |
| **Model** | Configured default model and provider |
| **Terminal** | Backend type (local, docker, ssh, etc.) |
| **API keys** | Presence check for all 22 provider/tool API keys |
| **Features** | Enabled toolsets, MCP server count, memory provider |
| **Services** | Gateway status, configured messaging platforms |
| **Workload** | Cron job counts, installed skill count |
| **Config overrides** | Any config values that differ from defaults |

### Example output

```
--- elidia dump ---
version:          0.8.0 (2026.4.8) [af4abd2f]
os:               Linux 6.14.0-37-generic x86_64
python:           3.11.14
openai_sdk:       2.24.0
profile:          default
elidia_home:      ~/.elidia
model:            anthropic/claude-opus-4.6
provider:         openrouter
terminal:         local

api_keys:
  openrouter           set
  openai               not set
  anthropic            set
  elidia                 not set
  firecrawl            set
  ...

features:
  toolsets:           all
  mcp_servers:        0
  memory_provider:    built-in
  gateway:            running (systemd)
  platforms:          telegram, discord
  cron_jobs:          3 active / 5 total
  skills:             42

config_overrides:
  agent.max_turns: 250
  compression.threshold: 0.85
  display.streaming: True
--- end dump ---
```

### When to use

- Reporting a bug on GitHub — paste the dump into your issue
- Asking for help in Discord — share it in a code block
- Comparing your setup to someone else's
- Quick sanity check when something isn't working

> [!TIP]
> `elidia dump` is specifically designed for sharing. For interactive diagnostics, use `elidia doctor`. For a visual overview, use `elidia status`.


## `elidia debug`

```bash
elidia debug share [options]
```

Upload a debug report (system info + recent logs) to a paste service and get a shareable URL. Useful for quick support requests — includes everything a helper needs to diagnose your issue.

| Option | Description |
|--------|-------------|
| `--lines <N>` | Number of log lines to include per log file (default: 200). |
| `--expire <days>` | Paste expiry in days (default: 7). |
| `--local` | Print the report locally instead of uploading. |

The report includes system info (OS, Python version, Elidia version), recent agent and gateway logs (512 KB limit per file), and redacted API key status. Keys are always redacted — no secrets are uploaded.

Paste services tried in order: paste.rs, dpaste.com.

### Examples

```bash
elidia debug share              # Upload debug report, print URL
elidia debug share --lines 500  # Include more log lines
elidia debug share --expire 30  # Keep paste for 30 days
elidia debug share --local      # Print report to terminal (no upload)
```

## `elidia backup`

```bash
elidia backup [options]
```

Create a zip archive of your Elidia configuration, skills, sessions, and data. The backup excludes the elidia-agent codebase itself.

| Option | Description |
|--------|-------------|
| `-o`, `--output <path>` | Output path for the zip file (default: `~/elidia-backup-<timestamp>.zip`). |
| `-q`, `--quick` | Quick snapshot: only critical state files (config.yaml, state.db, .env, auth, cron jobs). Much faster than a full backup. |
| `-l`, `--label <name>` | Label for the snapshot (only used with `--quick`). |

The backup uses SQLite's `backup()` API for safe copying, so it works correctly even when Elidia is running (WAL-mode safe).

**What's excluded from the zip:**

- `*.db-wal`, `*.db-shm`, `*.db-journal` — SQLite's WAL / shared-memory / journal sidecars. The `*.db` file already got a consistent snapshot via `sqlite3.backup()`; shipping the live sidecars alongside it would let a restore see a half-committed state.
- `checkpoints/` — per-session trajectory caches. Hash-keyed and regenerated per session; wouldn't port cleanly to another install anyway.
- The `elidia-agent` code itself (this is a user-data backup, not a repo snapshot).

### Examples

```bash
elidia backup                           # Full backup to ~/elidia-backup-*.zip
elidia backup -o /tmp/elidia.zip        # Full backup to specific path
elidia backup --quick                   # Quick state-only snapshot
elidia backup --quick --label "pre-upgrade"  # Quick snapshot with label
```

## `elidia checkpoints`

```bash
elidia checkpoints [COMMAND]
```

Inspect and manage the shadow git store at `~/.elidia/checkpoints/` — the storage layer behind the in-session `/rollback` command. Safe to run any time; does not require the agent to be running.

| Subcommand | Description |
|------------|-------------|
| `status` (default) | Show total size, project count, and per-project breakdown. Bare `elidia checkpoints` is equivalent. |
| `list` | Alias for `status`. |
| `prune` | Force a cleanup sweep — delete orphan and stale projects, GC the store, enforce the size cap. Ignores the 24h idempotency marker. |
| `clear` | Delete the entire checkpoint base. Irreversible; asks for confirmation unless `-f`. |
| `clear-legacy` | Delete only the `legacy-<timestamp>/` archives produced by the v1→v2 migration. |

### Options

| Option | Subcommand | Description |
|--------|------------|-------------|
| `--limit N` | `status`, `list` | Max projects to list (default 20). |
| `--retention-days N` | `prune` | Drop projects whose `last_touch` is older than N days (default 7). |
| `--max-size-mb N` | `prune` | After the orphan/stale pass, drop the oldest commit per project until total store size ≤ N MB (default 500). |
| `--keep-orphans` | `prune` | Skip deleting projects whose working directory no longer exists. |
| `-f`, `--force` | `clear`, `clear-legacy` | Skip the confirmation prompt. |

### Examples

```bash
elidia checkpoints                                  # status overview
elidia checkpoints prune --retention-days 3         # aggressive cleanup
elidia checkpoints prune --max-size-mb 200          # tighten size cap once
elidia checkpoints clear-legacy -f                  # drop v1 archive dirs
elidia checkpoints clear -f                         # wipe everything
```

See [Checkpoints and `/rollback`](https://aiutils.io/elidia/user-guide/checkpoints-and-rollback) for the full architecture and the in-session commands.

## `elidia import`

```bash
elidia import <zipfile> [options]
```

Restore a previously created Elidia backup into your Elidia home directory. All files in the archive overwrite existing files in your Elidia home; `--force` only skips the confirmation prompt that fires when the target already has an Elidia installation.

| Option | Description |
|--------|-------------|
| `-f`, `--force` | Skip the existing-installation confirmation prompt. |

> [!WARNING]
> Stop the gateway before importing to avoid conflicts with running processes.


### Examples
```bash
elidia import ~/elidia-backup-20260423.zip           # Prompts before overwriting existing config
elidia import ~/elidia-backup-20260423.zip --force   # Overwrite without prompting
```

## `elidia logs`

```bash
elidia logs [log_name] [options]
```

View, tail, and filter Elidia log files. All logs are stored in `~/.elidia/logs/` (or `<profile>/logs/` for non-default profiles).

### Log files

| Name | File | What it captures |
|------|------|-----------------|
| `agent` (default) | `agent.log` | All agent activity — API calls, tool dispatch, session lifecycle (INFO and above) |
| `errors` | `errors.log` | Warnings and errors only — a filtered subset of agent.log |
| `gateway` | `gateway.log` | Messaging gateway activity — platform connections, message dispatch, webhook events |
| `gui` | `gui.log` | Dashboard / TUI-gateway / PTY-bridge / websocket events |
| `desktop` | `desktop.log` | Electron desktop app — boot, backend spawn output, and recent Python tracebacks |

### Options

| Option | Description |
|--------|-------------|
| `log_name` | Which log to view: `agent` (default), `errors`, `gateway`, or `list` to show available files with sizes. |
| `-n`, `--lines <N>` | Number of lines to show (default: 50). |
| `-f`, `--follow` | Follow the log in real time, like `tail -f`. Press Ctrl+C to stop. |
| `--level <LEVEL>` | Minimum log level to show: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `--session <ID>` | Filter lines containing a session ID substring. |
| `--since <TIME>` | Show lines from a relative time ago: `30m`, `1h`, `2d`, etc. Supports `s` (seconds), `m` (minutes), `h` (hours), `d` (days). |
| `--component <NAME>` | Filter by component: `gateway`, `agent`, `tools`, `cli`, `cron`. |

### Examples

```bash
# View the last 50 lines of agent.log (default)
elidia logs

# Follow agent.log in real time
elidia logs -f

# View the last 100 lines of gateway.log
elidia logs gateway -n 100

# Show only warnings and errors from the last hour
elidia logs --level WARNING --since 1h

# Filter by a specific session
elidia logs --session abc123

# Follow errors.log, starting from 30 minutes ago
elidia logs errors --since 30m -f

# List all log files with their sizes
elidia logs list
```

### Filtering

Filters can be combined. When multiple filters are active, a log line must pass **all** of them to be shown:

```bash
# WARNING+ lines from the last 2 hours containing session "tg-12345"
elidia logs --level WARNING --since 2h --session tg-12345
```

Lines without a parseable timestamp are included when `--since` is active (they may be continuation lines from a multi-line log entry). Lines without a detectable level are included when `--level` is active.

### Log rotation

Elidia uses Python's `RotatingFileHandler`. Old logs are rotated automatically — look for `agent.log.1`, `agent.log.2`, etc. The `elidia logs list` subcommand shows all log files including rotated ones.


## `elidia prompt-size`

```bash
elidia prompt-size [--platform <name>] [--json]
```

Reports the fixed prompt budget for a fresh session — what gets sent on every
API call *before* any conversation content. Useful when a downstream adapter or
proxy has a tighter prompt budget than the model's context window, or when you
want to see which block (skills index, memory, profile) dominates.

It builds the same system prompt the agent would, then breaks it down:

- **System prompt total** — full assembled prompt (identity, guidance, skills
  index, context files, memory, profile, timestamp).
- **Skills index** — the `<available_skills>` block. This is often the largest
  single block when many skills are installed.
- **Memory** and **user profile** — your `MEMORY.md` / `USER.md` snapshots.
- **Prompt tiers** — stable / context / volatile, matching how Elidia layers
  the prompt for cache-friendliness.
- **Tool schemas** — the JSON for all enabled tools (the other half of the
  fixed per-call payload).

Runs entirely offline — no API call, works with no credentials configured.

```bash
# Human-readable breakdown for the CLI platform (default)
elidia prompt-size

# Simulate a messaging platform's prompt (different platform hint)
elidia prompt-size --platform telegram

# Machine-readable output for scripts
elidia prompt-size --json
```

> [!TIP]
> The skills index and tool schemas scale with how many skills and tools you have
> enabled. To shrink the prompt, disable unused toolsets (`elidia tools`) or
> uninstall skills you don't need (`elidia skills`). Context files (AGENTS.md,
> .cursorrules) in your current directory also count toward the total.


## `elidia config`

```bash
elidia config <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `show` | Show current config values. |
| `edit` | Open `config.yaml` in your editor. |
| `set <key> <value>` | Set a config value. |
| `path` | Print the config file path. |
| `env-path` | Print the `.env` file path. |
| `check` | Check for missing or stale config. |
| `migrate` | Add newly introduced options interactively. |

## `elidia pairing`

```bash
elidia pairing <list|approve|revoke|clear-pending>
```

| Subcommand | Description |
|------------|-------------|
| `list` | Show pending and approved users. |
| `approve <platform> <code>` | Approve a pairing code. |
| `revoke <platform> <user-id>` | Revoke a user's access. |
| `clear-pending` | Clear pending pairing codes. |

## `elidia skills`

```bash
elidia skills <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `browse` | Paginated browser for skill registries. |
| `search` | Search skill registries. |
| `install` | Install a skill. |
| `inspect` | Preview a skill without installing it. |
| `list` | List installed skills. |
| `check` | Check installed hub skills for upstream updates. |
| `update` | Reinstall hub skills with upstream changes when available. |
| `audit` | Re-scan installed hub skills. |
| `uninstall` | Remove a hub-installed skill. |
| `reset` | Un-stick a bundled skill flagged as `user_modified` by clearing its manifest entry. With `--restore`, also replaces the user copy with the bundled version. |
| `opt-out` | Stop bundled skills from being seeded into the active profile. Writes a `.no-bundled-skills` marker so the installer, `elidia update`, and any sync skip bundled-skill seeding. Safe by default — nothing on disk is touched. With `--remove`, also deletes already-present bundled skills that are **unmodified** (user-edited, hub-installed, and hand-written skills are never removed; previews and confirms first, `--yes` to skip). |
| `opt-in` | Undo `opt-out` by removing the `.no-bundled-skills` marker so bundled skills are seeded again on the next `elidia update`. With `--sync`, re-seed immediately. |
| `publish` | Publish a skill to a registry. |
| `snapshot` | Export/import skill configurations. |
| `tap` | Manage custom skill sources. |
| `config` | Interactive enable/disable configuration for skills by platform. |

Common examples:

```bash
elidia skills browse
elidia skills browse --source official
elidia skills search react --source skills-sh
elidia skills search https://mintlify.com/docs --source well-known
elidia skills inspect official/security/1password
elidia skills inspect skills-sh/vercel-labs/json-render/json-render-react
elidia skills install official/migration/openclaw-migration
elidia skills install skills-sh/anthropics/skills/pdf --force
elidia skills install https://sharethis.chat/SKILL.md                     # Direct URL (single-file SKILL.md)
elidia skills install https://example.com/SKILL.md --name my-skill        # Override name when frontmatter has none
elidia skills check
elidia skills update
elidia skills config
elidia skills reset google-workspace
elidia skills reset google-workspace --restore --yes
elidia skills opt-out                  # stop future bundled-skill seeding (nothing deleted)
elidia skills opt-out --remove --yes   # also delete UNMODIFIED bundled skills
elidia skills opt-in --sync            # undo: remove marker and re-seed now
```

Notes:
- `--force` can override non-dangerous policy blocks for third-party/community skills.
- `--force` does not override a `dangerous` scan verdict.
- `--source skills-sh` searches the public `skills.sh` directory.
- `--source well-known` lets you point Elidia at a site exposing `/.well-known/skills/index.json`.
- `--source browse-sh` searches [browse.sh](https://browse.sh)'s catalog of 200+ site-specific browser-automation skills. Identifiers look like `browse-sh/airbnb.com/search-listings-ddgioa`.
- Passing an `http(s)://…/*.md` URL installs a single-file SKILL.md directly. When frontmatter has no `name:` and the URL slug isn't a valid identifier, an interactive terminal prompts for a name; non-interactive surfaces (`/skills install` inside the TUI, gateway platforms) require `--name <x>` instead.

## `elidia bundles`

```bash
elidia bundles <subcommand>
```

Skill bundles group several skills under one `/<bundle-name>` slash command. Invoking the bundle loads every referenced skill into a single combined user message. Storage: `~/.elidia/skill-bundles/<slug>.yaml`. See [Skill Bundles](skills.md) for the YAML schema and behavior.

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `list` | List installed bundles (default when no subcommand given) |
| `show <name>` | Show one bundle's name, description, skills, and file path |
| `create <name>` | Create a new bundle. Pass `--skill <id>` (repeat) or omit for interactive entry. `--description`, `--instruction`, `--force` available. |
| `delete <name>` | Remove a bundle file |
| `reload` | Re-scan `~/.elidia/skill-bundles/` and report added/removed bundles |

Examples:

```bash
elidia bundles create backend-dev \
  --skill github-code-review \
  --skill test-driven-development \
  --skill github-pr-workflow \
  -d "Backend feature work"

elidia bundles list
elidia bundles show backend-dev
elidia bundles delete backend-dev
```

In a chat session, `/bundles` lists installed bundles and `/<bundle-name>` loads one.

## `elidia curator`

```bash
elidia curator <subcommand>
```

The curator is an auxiliary-model background task that periodically reviews agent-created skills, prunes stale ones, consolidates overlaps, and archives obsolete skills. Bundled and hub-installed skills are never touched. Archives are recoverable; auto-deletion never happens.

| Subcommand | Description |
|------------|-------------|
| `status` | Show curator status and skill stats |
| `run` | Trigger a curator review now (blocks until the LLM pass finishes) |
| `run --background` | Start the LLM pass in a background thread and return immediately |
| `run --dry-run` | Preview only — produce the review report with no mutations |
| `backup` | Take a manual tar.gz snapshot of `~/.elidia/skills/` (curator also snapshots automatically before every real run) |
| `rollback` | Restore `~/.elidia/skills/` from a snapshot (defaults to newest) |
| `rollback --list` | List available snapshots |
| `rollback --id <ts>` | Restore a specific snapshot by id |
| `rollback -y` | Skip the confirmation prompt |
| `pause` | Pause the curator until resumed |
| `resume` | Resume a paused curator |
| `pin <skill>` | Pin a skill so the curator never auto-transitions it |
| `unpin <skill>` | Unpin a skill |
| `restore <skill>` | Restore an archived skill |
| `archive <skill>` | Archive a skill manually |
| `prune` | Manually prune skills the curator would normally clean up |
| `list-archived` | List archived skills (recoverable via `restore`) |

On a fresh install the first scheduled pass is deferred by one full `interval_hours` (7 days by default) — the gateway will not curate immediately on the first tick after `elidia update`. Use `elidia curator run --dry-run` to preview before that happens.

See [Curator](https://aiutils.io/elidia/user-guide/features/curator) for behavior and config.

## `elidia fallback`

```bash
elidia fallback <subcommand>
```

Manage the fallback provider chain. Fallback providers are tried in order when the primary model fails with rate-limit, overload, or connection errors.

| Subcommand | Description |
|------------|-------------|
| `list` (alias: `ls`) | Show the current fallback chain (default when no subcommand) |
| `add` | Pick a provider + model (same picker as `elidia model`) and append to the chain |
| `remove` (alias: `rm`) | Pick an entry to delete from the chain |
| `clear` | Remove all fallback entries |

See [Fallback Providers](https://aiutils.io/elidia/user-guide/features/fallback-providers).

## `elidia hooks`

```bash
elidia hooks <subcommand>
```

Inspect shell-script hooks declared in `~/.elidia/config.yaml`, test them against synthetic payloads, and manage the first-use consent allowlist at `~/.elidia/shell-hooks-allowlist.json`.

| Subcommand | Description |
|------------|-------------|
| `list` (alias: `ls`) | List configured hooks with matcher, timeout, and consent status |
| `test <event>` | Fire every hook matching `<event>` against a synthetic payload |
| `revoke` (aliases: `remove`, `rm`) | Remove a command's allowlist entries (takes effect on next restart) |
| `doctor` | Check each configured hook: exec bit, allowlist, mtime drift, JSON validity, and synthetic run timing |

See [Hooks](https://aiutils.io/elidia/user-guide/features/hooks) for event signatures and payload shapes.

## `elidia memory`

```bash
elidia memory <subcommand>
```

Set up and manage external memory provider plugins. Available providers: honcho, openviking, mem0, hindsight, holographic, retaindb, byterover, supermemory. Only one external provider can be active at a time. Built-in memory (MEMORY.md/USER.md) is always active.

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `setup` | Interactive provider selection and configuration. |
| `status` | Show current memory provider config. |
| `off` | Disable external provider (built-in only). |

> [!NOTE] Provider-specific subcommands
> When an external memory provider is active, it may register its own top-level `elidia <provider>` command for provider-specific management (e.g. `elidia honcho` when Honcho is active). Inactive providers do not expose their subcommands. Run `elidia --help` to see what's currently wired in.


## `elidia acp`

```bash
elidia acp
```

Starts Elidia as an ACP (Agent Client Protocol) stdio server for editor integration.

Related entrypoints:

```bash
elidia-acp
python -m acp_adapter
```

Install support first:

```bash
pip install -e '.[acp]'
```

See [ACP Editor Integration](https://aiutils.io/elidia/user-guide/features/acp) and [ACP Internals](https://aiutils.io/elidia/developer-guide/acp-internals).

## `elidia mcp`

```bash
elidia mcp <subcommand>
```

Manage MCP (Model Context Protocol) server configurations and run Elidia as an MCP server.

| Subcommand | Description |
|------------|-------------|
| *(none)* or `picker` | Interactive catalog picker — browse Elidia-approved MCPs and install/enable/disable. |
| `catalog` | List Elidia-approved MCPs (plain text, scriptable). |
| `install <name>` | Install a catalog entry (e.g. `elidia mcp install n8n`). |
| `serve [-v\|--verbose]` | Run Elidia as an MCP server — expose conversations to other agents. |
| `add <name> [--url URL] [--command CMD] [--args ...] [--auth oauth\|header]` | Add a custom MCP server with automatic tool discovery. |
| `remove <name>` (alias: `rm`) | Remove an MCP server from config. |
| `list` (alias: `ls`) | List configured MCP servers. |
| `test <name>` | Test connection to an MCP server. |
| `configure <name>` (alias: `config`) | Toggle tool selection for a server. |
| `login <name>` | Force re-authentication for an OAuth-based MCP server. |

See [MCP Config Reference](https://aiutils.io/elidia/reference/mcp-config-reference), [Use MCP with Elidia](https://aiutils.io/elidia/guides/use-mcp-with-elidia), and [MCP Server Mode](mcp.md).

## `elidia plugins`

```bash
elidia plugins [subcommand]
```

Unified plugin management — general plugins, memory providers, and context engines in one place. Running `elidia plugins` with no subcommand opens a composite interactive screen with two sections:

- **General Plugins** — multi-select checkboxes to enable/disable installed plugins
- **Provider Plugins** — single-select configuration for Memory Provider and Context Engine. Press ENTER on a category to open a radio picker.

| Subcommand | Description |
|------------|-------------|
| *(none)* | Composite interactive UI — general plugin toggles + provider plugin configuration. |
| `install <identifier> [--force]` | Install a plugin from a Git URL or `owner/repo`. |
| `update <name>` | Pull latest changes for an installed plugin. |
| `remove <name>` (aliases: `rm`, `uninstall`) | Remove an installed plugin. |
| `enable <name>` | Enable a disabled plugin. |
| `disable <name>` | Disable a plugin without removing it. |
| `list` (alias: `ls`) | List installed plugins with enabled/disabled status. |

Provider plugin selections are saved to `config.yaml`:
- `memory.provider` — active memory provider (empty = built-in only)
- `context.engine` — active context engine (`"compressor"` = built-in default)

General plugin disabled list is stored in `config.yaml` under `plugins.disabled`.

See [Plugins](https://aiutils.io/elidia/user-guide/features/plugins) and [Build an Elidia Plugin](https://aiutils.io/elidia/guides/build-a-elidia-plugin).

## `elidia tools`

```bash
elidia tools [--summary]
```

| Option | Description |
|--------|-------------|
| `--summary` | Print the current enabled-tools summary and exit. |

Without `--summary`, this launches the interactive per-platform tool configuration UI.

## `elidia computer-use`

```bash
elidia computer-use <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `install` | Run the upstream cua-driver installer (macOS only). |
| `install --upgrade` | Re-run the installer even if cua-driver is already on PATH. The upstream script always pulls the latest release, so this performs an in-place upgrade. |
| `status` | Print whether `cua-driver` is on `$PATH` and which version is installed. |

`elidia computer-use install` is the stable entry point for installing the
[cua-driver](https://github.com/trycua/cua) binary used by the
`computer_use` toolset. It runs the same upstream installer that
`elidia tools` invokes when you first enable Computer Use, so it's safe
to use for re-running the install if the toolset toggle didn't trigger
it (for example, on returning-user setups).

`elidia update` automatically re-runs the upstream installer at the end
of the update if cua-driver is on PATH, so most users will not need to
call `--upgrade` manually. Use it when upstream ships a fix you want
right now without waiting for the next Elidia update.

## `elidia sessions`

```bash
elidia sessions <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `list` | List recent sessions. |
| `browse` | Interactive session picker with search and resume. |
| `export <output> [--session-id ID]` | Export sessions to JSONL. |
| `delete <session-id>` | Delete one session. |
| `prune` | Delete old sessions. |
| `stats` | Show session-store statistics. |
| `rename <session-id> <title>` | Set or change a session title. |

## `elidia insights`

```bash
elidia insights [--days N] [--source platform]
```

| Option | Description |
|--------|-------------|
| `--days <n>` | Analyze the last `n` days (default: 30). |
| `--source <platform>` | Filter by source such as `cli`, `telegram`, or `discord`. |

## `elidia claw`

```bash
elidia claw migrate [options]
```

Migrate your OpenClaw setup to Elidia. Reads from `~/.openclaw` (or a custom path) and writes to `~/.elidia`. Automatically detects legacy directory names (`~/.clawdbot`, `~/.moltbot`) and config filenames (`clawdbot.json`, `moltbot.json`).

| Option | Description |
|--------|-------------|
| `--dry-run` | Preview what would be migrated without writing anything. |
| `--preset <name>` | Migration preset: `full` (all compatible settings) or `user-data` (excludes infrastructure config). Neither preset imports secrets — pass `--migrate-secrets` explicitly. |
| `--overwrite` | Overwrite existing Elidia files on conflicts (default: refuse to apply when the plan has conflicts). |
| `--migrate-secrets` | Include API keys in migration. Required even under `--preset full`. |
| `--no-backup` | Skip the pre-migration zip snapshot of `~/.elidia/` (by default a single restore-point archive is written to `~/.elidia/backups/pre-migration-*.zip` before apply; restorable with `elidia import`). |
| `--source <path>` | Custom OpenClaw directory (default: `~/.openclaw`). |
| `--workspace-target <path>` | Target directory for workspace instructions (AGENTS.md). |
| `--skill-conflict <mode>` | Handle skill name collisions: `skip` (default), `overwrite`, or `rename`. |
| `--yes` | Skip the confirmation prompt. |

### What gets migrated

The migration covers 30+ categories across persona, memory, skills, model providers, messaging platforms, agent behavior, session policies, MCP servers, TTS, and more. Items are either **directly imported** into Elidia equivalents or **archived** for manual review.

**Directly imported:** SOUL.md, MEMORY.md, USER.md, AGENTS.md, skills (4 source directories), default model, custom providers, MCP servers, messaging platform tokens and allowlists (Telegram, Discord, Slack, WhatsApp, Signal, Matrix, Mattermost), agent defaults (reasoning effort, compression, human delay, timezone, sandbox), session reset policies, approval rules, TTS config, browser settings, tool settings, exec timeout, command allowlist, gateway config, and API keys from 3 sources.

**Archived for manual review:** Cron jobs, plugins, hooks/webhooks, memory backend (QMD), skills registry config, UI/identity, logging, multi-agent setup, channel bindings, IDENTITY.md, TOOLS.md, HEARTBEAT.md, BOOTSTRAP.md.

**API key resolution** checks three sources in priority order: config values → `~/.openclaw/.env` → `auth-profiles.json`. All token fields handle plain strings, env templates (`${VAR}`), and SecretRef objects.

For the complete config key mapping, SecretRef handling details, and post-migration checklist, see the **[full migration guide](migrate-from-openclaw.md)**.

### Examples

```bash
# Preview what would be migrated
elidia claw migrate --dry-run

# Full migration (all compatible settings, no secrets)
elidia claw migrate --preset full

# Full migration including API keys
elidia claw migrate --preset full --migrate-secrets

# Migrate user data only (no secrets), overwrite conflicts
elidia claw migrate --preset user-data --overwrite

# Migrate from a custom OpenClaw path
elidia claw migrate --source /home/user/old-openclaw
```

## `elidia dashboard`

```bash
elidia dashboard [options]
```

Launch the web dashboard — a browser-based UI for managing configuration, API keys, and monitoring sessions. Requires `pip install elidia-agent[web]` (FastAPI + Uvicorn). The embedded browser Chat tab requires `--tui` plus the `pty` extra. See [Web Dashboard](https://aiutils.io/elidia/user-guide/features/web-dashboard) for full documentation.

| Option | Default | Description |
|--------|---------|-------------|
| `--port` | `9119` | Port to run the web server on |
| `--host` | `127.0.0.1` | Bind address |
| `--no-open` | — | Don't auto-open the browser |
| `--tui` | off | Enable the in-browser Chat tab by running `elidia --tui` behind a PTY/WebSocket bridge. Requires `pip install 'elidia-agent[web,pty]'` and a POSIX PTY environment such as Linux, macOS, or WSL2. |
| `--insecure` | off | Allow binding to non-localhost hosts. Exposes dashboard credentials on the network; use only behind trusted network controls. |
| `--stop` | — | Stop running `elidia dashboard` processes and exit. |
| `--status` | — | List running `elidia dashboard` processes and exit. |

```bash
# Default — opens browser to http://127.0.0.1:9119
elidia dashboard

# Custom port, no browser
elidia dashboard --port 8080 --no-open

# Enable the browser Chat tab
elidia dashboard --tui
```

## `elidia profile`

```bash
elidia profile <subcommand>
```

Manage profiles — multiple isolated Elidia instances, each with its own config, sessions, skills, and home directory.

| Subcommand | Description |
|------------|-------------|
| `list` | List all profiles. |
| `use <name>` | Set a sticky default profile. |
| `create <name> [--clone] [--clone-all] [--clone-from <source>] [--no-alias]` | Create a new profile. `--clone` copies config, `.env`, and `SOUL.md` from the active profile. `--clone-all` copies all state. `--clone-from` specifies a source profile. |
| `delete <name> [-y]` | Delete a profile. |
| `show <name>` | Show profile details (home directory, config, etc.). |
| `alias <name> [--remove] [--name NAME]` | Manage wrapper scripts for quick profile access. |
| `rename <old> <new>` | Rename a profile. |
| `export <name> [-o FILE]` | Export a profile to a `.tar.gz` archive (local backup). |
| `import <archive> [--name NAME]` | Import a profile from a `.tar.gz` archive (local restore). |
| `install <source> [--name N] [--alias] [--force] [-y]` | Install a profile distribution from a git URL or local directory. |
| `update <name> [--force-config] [-y]` | Re-pull a distribution; preserves user data (memories, sessions, auth). |
| `info <name>` | Show a profile's distribution manifest (version, requirements, source). |

Examples:

```bash
elidia profile list
elidia profile create work --clone
elidia profile use work
elidia profile alias work --name h-work
elidia profile export work -o work-backup.tar.gz
elidia profile import work-backup.tar.gz --name restored
elidia profile install github.com/user/my-distro --alias
elidia profile update work
elidia -p work chat -q "Hello from work profile"
```

## `elidia completion`

```bash
elidia completion [bash|zsh|fish]
```

Print a shell completion script to stdout. Source the output in your shell profile for tab-completion of Elidia commands, subcommands, and profile names.

Examples:

```bash
# Bash
elidia completion bash >> ~/.bashrc

# Zsh
elidia completion zsh >> ~/.zshrc

# Fish
elidia completion fish > ~/.config/fish/completions/elidia.fish
```

## `elidia update`

```bash
elidia update [--gateway] [--check] [--no-backup] [--backup] [--yes]
```

Pulls the latest `elidia-agent` code and reinstalls dependencies in your venv, then re-runs the post-install hooks (MCP servers, skills sync, completion install). Safe to run on a live install.

**pip installs:** `elidia update` detects pip-based installations automatically — it queries PyPI for the latest release and runs `pip install --upgrade elidia-agent` instead of `git pull`. PyPI releases track tagged versions (major/minor releases), not every commit on `main`. Use `--check` to see if a newer PyPI release is available without installing.

| Option | Description |
|--------|-------------|
| `--gateway` | Internal mode used by the messaging `/update` command. Uses file-based IPC for prompts and progress streaming instead of reading from terminal stdin. Not a gateway restart flag. |
| `--check` | Check whether an update is available without pulling, installing dependencies, or restarting anything. |
| `--no-backup` | Skip the pre-update backup for this run, even if `updates.pre_update_backup` is enabled in `config.yaml`. |
| `--backup` | Create a labeled pre-update snapshot of `ELIDIA_HOME` (config, auth, sessions, skills, pairing data) before pulling. Default is **off** — the previous always-backup behavior was adding minutes to every update on large homes. Flip it on permanently via `updates.pre_update_backup: true` in `config.yaml`. |
| `--yes`, `-y` | Assume yes for interactive prompts such as config migration and stash restore. API-key entry is skipped; run `elidia config migrate` separately for those. |

Additional behavior:

- **Gateway restart.** After a successful update, Elidia attempts to restart all running gateway profiles automatically so they pick up the new code. Use `elidia gateway restart` when you want to restart a gateway without applying an update.
- **Pairing data snapshot.** Even when `--backup` is off, `elidia update` takes a lightweight snapshot of `~/.elidia/pairing/` and the Feishu comment rules before `git pull`. You can roll it back with `elidia backup restore --state pre-update` if a pull rewrites a file you were editing.
- **Legacy `elidia.service` warning.** If Elidia detects a pre-rename `elidia.service` systemd unit (instead of the current `elidia-gateway.service`), it prints a one-time migration hint so you can avoid flap-loop issues.
- **Exit codes.** `0` on success, `1` on pull/install/post-install errors, `2` on unexpected working-tree changes that block `git pull`.

## Maintenance commands

| Command | Description |
|---------|-------------|
| `elidia version` | Print version information. |
| `elidia update` | Pull latest changes and reinstall dependencies. |
| `elidia postinstall` | Internal bootstrap. Runs once after `pip install elidia-agent` (or `elidia update` on pip installs) to install non-Python dependencies that pip cannot provide — Node.js runtime, headless browser, ripgrep, ffmpeg — and then trigger `elidia setup` if the profile has not been configured yet. Safe to re-run idempotently. |
| `elidia uninstall [--full] [--yes]` | Remove Elidia, optionally deleting all config/data. |

## See also

- [Slash Commands Reference](https://aiutils.io/elidia/reference/slash-commands)
- [CLI Interface](cli.md)
- [Sessions](https://aiutils.io/elidia/user-guide/sessions)
- [Skills System](skills.md)
- [Skins & Themes](https://aiutils.io/elidia/user-guide/features/skins)
