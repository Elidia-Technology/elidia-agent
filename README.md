<p align="center">
  <img src="https://aiutils.io/images/elidia-lockup-dark.png" alt="Elidia Agent">
</p>



<p align="center">
  <a href="https://pypi.org/project/elidia-agent-cli/"><img src="https://img.shields.io/pypi/v/elidia-agent-cli?style=for-the-badge&label=PyPI&color=3775A9" alt="PyPI"></a>
  <a href="https://aiutils.io/elidia"><img src="https://img.shields.io/badge/Docs-aiutils.io-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="https://developer.aiutils.io"><img src="https://img.shields.io/badge/Developer%20Console-developer.aiutils.io-3775A9?style=for-the-badge" alt="Developer Console"></a>
  <a href="https://aiutils.io"><img src="https://img.shields.io/badge/Powered%20by-Elidia%20Technology-blueviolet?style=for-the-badge" alt="Powered by Elidia Technology"></a>
  <a href="README.in.md"><img src="https://img.shields.io/badge/Lang-Hindi-orange?style=for-the-badge" alt="हिन्दी"></a>
</p>

**Elidia Agent** is a multi-platform AI agent for your terminal and messaging apps. It is part of the [AiUtils.io](https://aiutils.io) ecosystem and powered by **Elidia Technology Pvt. Ltd.**

Use it with the model provider you already work with — [Elidia Portal](https://developer.aiutils.io), [OpenRouter](https://openrouter.ai) (200+ models), [NovitaAI](https://novita.ai), [NVIDIA NIM](https://build.nvidia.com), [Xiaomi MiMo](https://platform.xiaomimimo.com), [z.ai/GLM](https://z.ai), [Kimi/Moonshot](https://platform.moonshot.ai), [MiniMax](https://www.minimax.io), [Hugging Face](https://huggingface.co), OpenAI, or your own endpoint. Switch with `elidia model` — no code changes, no lock-in.

## ✨ Features

| | |
| --- | --- |
| 🖥️ **Terminal interface** | Interactive TUI with multiline editing, slash-command autocomplete, conversation history, and streaming tool output. |
| 📱 **Messaging platforms** | Telegram, Discord, Slack, WhatsApp, Signal, and CLI — all from a single gateway. |
| 🧠 **Memory & skills** | Remembers across sessions, creates reusable skills, and works with the [agentskills.io](https://agentskills.io) open standard. |
| ⏰ **Scheduled tasks** | Built-in cron for daily reports, backups, and audits — described in plain language. |
| 🧩 **Subagents** | Spawn isolated subagents to handle work in parallel. |
| ☁️ **Flexible deployment** | Run locally, in Docker, over SSH, or on serverless backends (Modal, Daytona). |
| 🔬 **Research tooling** | Batch trajectory generation and compression for training tool-calling models. |

---

## 🚀 Install

Requires **Python 3.11–3.13**.

```bash
pip install elidia-agent-cli
```

Prefer an isolated tool environment? Use [uv](https://docs.astral.sh/uv/) (recommended) or [pipx](https://pipx.pypa.io/):

```bash
uv tool install elidia-agent-cli
# or
pipx install elidia-agent-cli
```

To include every optional backend in one go (messaging platforms, web search, image generation, TTS, and more):

```bash
pip install "elidia-agent-cli[all]"
```

Then start:

```bash
elidia              # start chatting
```

> [!NOTE]
> **Android / Termux:** see the [Termux guide](docs/termux.md). On Termux, install the curated extra that skips Android-incompatible voice dependencies:
>
> ```bash
> pip install "elidia-agent-cli[termux]"
> ```

Full installation details: [docs/installation.md](docs/installation.md).

---

## 🏁 Getting Started

```bash
elidia              # Interactive CLI — start a conversation
elidia model        # Choose your LLM provider and model
elidia tools        # Configure which tools are enabled
elidia config set   # Set individual config values
elidia gateway      # Start the messaging gateway (Telegram, Discord, etc.)
elidia setup        # Run the full setup wizard
elidia claw migrate # Migrate from OpenClaw
elidia update       # Update to the latest version
elidia doctor       # Diagnose any issues
```

📖 **[Full documentation →](https://aiutils.io/elidia)** — or browse the in-repo guides below.

---

## 🎁 One subscription for everything — Elidia Portal

Elidia works with any provider. If you'd rather not manage separate API keys for the model, web search, image generation, TTS, and a cloud browser, **[Elidia Portal](https://developer.aiutils.io)** covers them under one subscription:

- **300+ LLMs** — pick any with `/model <name>`
- **1400+ Generative Models** — generate images, videos, audio, and 3D content
- **Tool Gateway** — web search (Firecrawl), image/video/audio/3D generation, text-to-speech (OpenAI), cloud browser (Browser Use), all routed through your subscription.

One command from a fresh install:

```bash
elidia setup --portal
```

That signs you in via OAuth, sets Elidia as your provider, and switches on the Tool Gateway. Check what's connected at any time with `elidia portal info`. Full details: [docs/elidia-portal.md](docs/elidia-portal.md) and [docs/tool-gateway.md](docs/tool-gateway.md).

You can still bring your own keys per-tool whenever you like — the gateway is per-backend, not all-or-nothing.

---

## 🧭 CLI vs Messaging — Quick Reference

Elidia has two entry points: start the terminal UI with `elidia`, or run the gateway and talk to it from Telegram, Discord, Slack, WhatsApp, Signal, or Email. Many slash commands work the same in both.

| Action                         | CLI                                           | Messaging platforms                                                              |
| ------------------------------ | --------------------------------------------- | -------------------------------------------------------------------------------- |
| Start chatting                 | `elidia`                                      | Run `elidia gateway setup` + `elidia gateway start`, then send the bot a message |
| Start fresh conversation       | `/new` or `/reset`                            | `/new` or `/reset`                                                               |
| Change model                   | `/model [provider:model]`                     | `/model [provider:model]`                                                        |
| Set a personality              | `/personality [name]`                         | `/personality [name]`                                                            |
| Retry or undo the last turn    | `/retry`, `/undo`                             | `/retry`, `/undo`                                                                |
| Compress context / check usage | `/compress`, `/usage`, `/insights [--days N]` | `/compress`, `/usage`, `/insights [days]`                                        |
| Browse skills                  | `/skills` or `/<skill-name>`                  | `/<skill-name>`                                                                  |
| Interrupt current work         | `Ctrl+C` or send a new message                | `/stop` or send a new message                                                    |
| Platform-specific status       | `/platforms`                                  | `/status`, `/sethome`                                                            |

For the full command lists, see the [CLI guide](docs/cli.md) and the [Messaging Gateway guide](docs/messaging.md).

---

## 📚 Documentation

All documentation lives at **[aiutils.io/elidia](https://aiutils.io/elidia)** and as Markdown files in this repository's [`docs/`](docs/README.md) folder:

| Section                                                                    | What's Covered                                             |
| -------------------------------------------------------------------------- | ---------------------------------------------------------- |
| [Installation](docs/installation.md)                                       | Linux, macOS, WSL2, Windows, Termux                        |
| [Quickstart](docs/quickstart.md)                                           | Install → setup → first conversation in 2 minutes          |
| [CLI Usage](docs/cli.md)                                                   | Commands, keybindings, personalities, sessions             |
| [Configuration](docs/configuration.md)                                     | Config file, providers, models, all options                |
| [Messaging Gateway](docs/messaging.md)                                     | Telegram, Discord, Slack, WhatsApp, Signal, and more       |
| [Security](docs/security.md)                                               | Command approval, DM pairing, container isolation          |
| [Tools & Toolsets](docs/tools.md)                                          | 40+ tools, toolset system, terminal backends               |
| [Skills System](docs/skills.md)                                            | Procedural memory, Skills Hub, creating skills             |
| [Memory](docs/memory.md)                                                   | Persistent memory, user profiles, best practices           |
| [MCP Integration](docs/mcp.md)                                             | Connect any MCP server for extended capabilities           |
| [Cron Scheduling](docs/cron.md)                                            | Scheduled tasks with platform delivery                     |
| [Context Files](docs/context-files.md)                                     | Project context that shapes every conversation             |
| [Elidia Portal](docs/elidia-portal.md)                                     | One subscription, 1400+ LLMs & Models, Tool Gateway                |
| [Migrating from OpenClaw](docs/migrate-from-openclaw.md)                   | Import settings, memories, skills, and API keys            |
| [Architecture](docs/architecture.md)                                       | Project structure, agent loop, key classes                 |
| [Contributing](docs/contributing.md)                                       | Development setup, PR process, code style                  |
| [CLI Reference](docs/cli-commands.md)                                      | All commands and flags                                     |
| [Environment Variables](docs/environment-variables.md)                     | Complete env var reference                                 |

---

## 🔄 Migrating from OpenClaw

If you're coming from OpenClaw, Elidia can import your settings, memories, skills, and API keys.

**During first-time setup:** the setup wizard (`elidia setup`) detects `~/.openclaw` and offers to migrate before configuration begins.

**Anytime after install:**

```bash
elidia claw migrate              # Interactive migration (full preset)
elidia claw migrate --dry-run    # Preview what would be migrated
elidia claw migrate --preset user-data   # Migrate without secrets
elidia claw migrate --overwrite  # Overwrite existing conflicts
```

What gets imported:

- **SOUL.md** — persona file
- **Memories** — MEMORY.md and USER.md entries
- **Skills** — user-created skills → `~/.elidia/skills/openclaw-imports/`
- **Command allowlist** — approval patterns
- **Messaging settings** — platform configs, allowed users, working directory
- **API keys** — allowlisted secrets (Telegram, OpenRouter, OpenAI, Anthropic, ElevenLabs)
- **TTS assets** — workspace audio files
- **Workspace instructions** — AGENTS.md (with `--workspace-target`)

See [docs/migrate-from-openclaw.md](docs/migrate-from-openclaw.md) for the complete guide.

---

## 📦 Repository & Releases

This public repository hosts the **packaged releases and documentation** for Elidia Agent. The source code is developed in a private repository and distributed as build artefacts on [PyPI](https://pypi.org/project/elidia-agent-cli/).

- **Latest release:** see the [Releases](https://github.com/Elidia-Technology/elidia-agent/releases) page for the current `.whl` and `.tar.gz` build artefacts.
- **All-platform downloads:** desktop installers (macOS `.dmg`, Windows `.exe`/`.msi`, Linux `.deb`/`.AppImage`/`.rpm`), Android (`.apk` + `.aab`), and the VS Code extension (Marketplace: `ElidiaTechnology.elidia-agent-vscode`) are published on [aiutils.io/elidia](https://aiutils.io/elidia).
- **Documentation:** [aiutils.io/elidia](https://aiutils.io/elidia)
- **Developer console:** [developer.aiutils.io](https://developer.aiutils.io)
- **Report a bug / request a feature:** open an [Issue](https://github.com/Elidia-Technology/elidia-agent/issues)

Contributions are welcome — see the [Contributing Guide](docs/contributing.md) for code style and the PR process. Since this repository does not host source code, please raise issues here rather than opening code PRs against it.


---

## 📄 License

MIT — see [LICENSE](LICENSE).

---

Built with ❤️ by [Elidia Technology Pvt. Ltd.](https://aiutils.io) — part of the [AiUtils.io](https://aiutils.io) ecosystem.
