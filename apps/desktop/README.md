<p align="center">
  <img src="https://aiutils.io/images/elidia-lockup-dark.png" alt="Elidia Agent" >
</p>


# Elidia Desktop

<p align="center">
  <a href="https://github.com/Elidia-Technology/elidia-agent/releases"><img src="https://img.shields.io/badge/Download-macOS%20%C2%B7%20Windows%20%C2%B7%20Linux-FFD700?style=for-the-badge" alt="Download"></a>
  <a href="https://aiutils.io/elidia"><img src="https://img.shields.io/badge/Docs-aiutils.io-FFD700?style=for-the-badge" alt="Documentation"></a>
  <a href="https://discord.gg/AiUtils"><img src="https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord"></a>
  <a href="https://github.com/Elidia-Technology/elidia-agent/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="License: MIT"></a>
</p>

**The native desktop app for [Elidia Agent](../../README.md) — the multi-platform AI agent from [AiUtils.io](https://aiutils.io).** Same agent, same skills, same memory as the CLI and gateway, in a polished native window — chat with streaming tool output, side-by-side previews, a file browser, voice, and settings, no terminal required. Available for **macOS, Windows, and Linux**.

<table>
<tr><td><b>Chat with the full agent</b></td><td>Streaming responses, live tool activity, structured tool summaries, and the same conversation history as every other Elidia surface.</td></tr>
<tr><td><b>Side-by-side previews</b></td><td>Render web pages, files, and tool outputs in a right-hand pane while you keep chatting.</td></tr>
<tr><td><b>File browser</b></td><td>Explore and preview the working directory without leaving the app.</td></tr>
<tr><td><b>Voice</b></td><td>Talk to Elidia and hear it back.</td></tr>
<tr><td><b>Settings & onboarding</b></td><td>Manage providers, models, tools, and credentials from a real UI. First-run setup gets you to your first message in seconds.</td></tr>
<tr><td><b>Stays current</b></td><td>Built-in updates pull the latest agent and rebuild the app in place.</td></tr>
</table>

---

## Install

### Install with Elidia (recommended)

Add `--include-desktop` to the [one-line installer](../../README.md#quick-install) and it sets up the agent and builds the desktop app in one go:

```bash
curl -fsSL https://raw.githubusercontent.com/Elidia-Technology/elidia-agent/main/scripts/install.sh | bash -s -- --include-desktop
```

Already have the Elidia CLI? Just run:

```bash
elidia desktop
```

It builds and launches the GUI against your existing install — same config, keys, sessions, and skills. On first launch Elidia walks you through picking a provider and model; nothing else to configure.

### Prebuilt installers

When a release ships desktop installers they're attached to its [releases page](https://github.com/Elidia-Technology/elidia-agent/releases) — `.dmg` (macOS), `.exe` / `.msi` (Windows), `.AppImage` / `.deb` / `.rpm` (Linux). These are published manually, so the install-with-Elidia path above is the most reliable way to get the latest.

---

## Updating

The app checks for updates in the background and offers a one-click update when one is ready. You can also update any time from the CLI:

```bash
elidia update
```

---

## Requirements

The installer handles everything for you (Python 3.11+, a portable Git, ripgrep). The only thing worth knowing:

- **Windows** — the installer bundles its own Git and Python; no admin rights or system changes required.
- **macOS / Linux** — uses your system Python 3.11+ (installed automatically if missing).

---

## Development

Want to hack on the app itself? Install workspace deps from the repo root once, then run the dev server from this directory:

```bash
npm install          # from repo root — links apps/desktop, web, apps/shared
cd apps/desktop
npm run dev          # Vite renderer + Electron, which boots the Python backend
```

Point the app at a specific source checkout, or sandbox it away from your real config:

```bash
ELIDIA_DESKTOP_ELIDIA_ROOT=/path/to/clone npm run dev
ELIDIA_HOME=/tmp/throwaway npm run dev
npm run dev:fake-boot   # exercise the startup overlay with deterministic delays
```

### Building installers

```bash
npm run dist:mac     # DMG + zip
npm run dist:win     # NSIS + MSI
npm run dist:linux   # AppImage + deb + rpm
npm run pack         # unpacked app under release/ (no installer)
```

Installers are built and uploaded to GitHub Releases manually. macOS/Windows signing & notarization happen automatically when the relevant credentials are present in the environment (`CSC_LINK` / `CSC_KEY_PASSWORD` / `APPLE_*` for macOS, `WIN_CSC_*` for Windows).

### How it works

The packaged app ships only the Electron shell. On first launch it installs the Elidia Agent runtime into `ELIDIA_HOME` (`~/.elidia`, or `%LOCALAPPDATA%\elidia` on Windows) — the **same layout a CLI install uses**, so the two are interchangeable. The renderer (React, in `src/`) talks to a `elidia dashboard --tui` backend over the standard gateway APIs and reuses the embedded TUI rather than reimplementing chat. The install, backend-resolution, and self-update logic all live in `electron/main.cjs`.

### Verification

Run before opening a PR (lint may surface pre-existing warnings but must exit cleanly):

```bash
npm run fix
npm run type-check
npm run lint
npm run test:desktop:all
```

### Troubleshooting

Boot logs land in `ELIDIA_HOME/logs/desktop.log` (includes backend output and recent Python tracebacks) — check it first if the app reports a boot failure.

**macOS / Linux:**

```bash
# Force a clean first-launch setup
rm "$HOME/.elidia/elidia-agent/.elidia-bootstrap-complete"
# Rebuild a broken Python venv
rm -rf "$HOME/.elidia/elidia-agent/venv"
# Reset a stuck macOS microphone prompt (macOS only)
tccutil reset Microphone com.aiutils.elidia
```

**Windows (PowerShell):**

```powershell
# Force a clean first-launch setup
Remove-Item "$env:LOCALAPPDATA\elidia\elidia-agent\.elidia-bootstrap-complete"
# Rebuild a broken Python venv
Remove-Item -Recurse -Force "$env:LOCALAPPDATA\elidia\elidia-agent\venv"
```

> The default Elidia home on Windows is `%LOCALAPPDATA%\elidia`. Set the `ELIDIA_HOME` env var if you've relocated it.

---

## Community

- 💬 [Discord](https://discord.gg/AiUtils)
- 📖 [Documentation](https://aiutils.io/elidia)
- 🐛 [Issues](https://github.com/Elidia-Technology/elidia-agent/issues)

---

## License

MIT — see [LICENSE](../../LICENSE).

Built by [AiUtils](https://aiutils.io).
