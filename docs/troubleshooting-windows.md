# Troubleshooting — Windows (and macOS / Linux)

This page collects the most common setup and runtime problems on **native
Windows**, where Elidia Agent runs the CLI, gateway, TUI, and tools directly
without WSL. Each symptom maps to its root cause and a concrete fix. A short
[macOS / Linux](#macos--linux) section covers the (much rarer) equivalents on
those platforms.

Start with [`elidia doctor`](#elidia-doctor) — it prints the detected install
layout, missing prerequisites, and the exact fix for most of these.

---

## Quick prerequisite matrix

| Requirement | Windows (native) | macOS | Linux | Needed for |
|---|---|---|---|---|
| Git for Windows / `bash` | **Required** — `C:\Program Files\Git\bin\bash.exe` (or `ELIDIA_GIT_BASH_PATH`) | preinstalled | preinstalled | terminal tool, shell commands |
| `uv` / `uvx` | required for uvx-based MCP | same | same | MCP servers launched with `uvx` |
| Node.js 22 (`npx`, `node`) | required for npx-based MCP + browser | same | same | MCP servers launched with `npx`, browser tool |

The one-line **PowerShell installer** provisions all of the above automatically
(`uv`, Python 3.11, Node.js 22, `ripgrep`, `ffmpeg`, and a portable Git Bash).
If you installed via `pip` or built from source, you must supply them yourself.

---

## Terminal: `ls -la` returns `[exit 1]` (or every command fails)

### Root cause

Windows ships an App Execution Alias named `bash.exe` under
`%LOCALAPPDATA%\Microsoft\WindowsApps` that forwards to **WSL**. When Git for
Windows is installed, only `Git\cmd` is added to PATH — not `Git\bin` — so the
WindowsApps alias sorts **ahead** of the real Git Bash on PATH. On a machine
with no working WSL distribution, that alias fails:

```
<3>WSL (2501 - Relay) ERROR: CreateProcessCommon:818: execvpe(/bin/bash) failed: No such file or directory
```

Elidia's terminal tool was resolving `bash` through the normal PATH lookup and
picking up that broken WSL alias, so `ls -la` (and every shell command)
surfaced as `[exit 1]`.

### Fix

Elidia now resolves Git for Windows **before** falling back to the PATH lookup,
and it skips the WindowsApps WSL alias entirely:

1. Ensure **Git for Windows** is installed: <https://git-scm.com/download/win>
   (installs `C:\Program Files\Git\bin\bash.exe`).
2. If Git is installed somewhere non-standard, point Elidia at it explicitly:

   ```powershell
   # In PowerShell (set persistently via System Properties → Environment Variables)
   $env:ELIDIA_GIT_BASH_PATH = "C:\Program Files\Git\bin\bash.exe"
   ```

   Or in `~/.elidia/.env`:

   ```bash
   ELIDIA_GIT_BASH_PATH=C:\Program Files\Git\bin\bash.exe
   ```

3. If you *want* WSL instead of native Git Bash, ensure a WSL distribution is
   actually installed (`wsl --install`), but Git for Windows is the supported
   native path.

### Verify

```powershell
& "C:\Program Files\Git\bin\bash.exe" -c "ls -la"
```

Must print a directory listing with exit code 0. Projects on other drives work
the same way — `/f/workspace` maps to `F:\workspace` automatically.

---

## MCP servers show "failed" or "disabled"

Elidia distinguishes two very different states (see also the
[MCP guide](mcp.md)):

- **`failed`** — the server *started* but the connection or discovery step
  failed. This is almost always a **missing executable**.
- **`disabled`** — the server is configured with `enabled: false`, or you have
  not installed it yet. This is expected until you enable/install it.

### Missing executable (`uvx`, `npx`, `node`)

Many stdio MCP servers are launched via `uvx` (Python) or `npx` (Node). If the
command isn't on PATH, the connect error now names the missing executable and
tells you what to install:

```
missing executable 'uvx' — install uv (https://docs.astral.sh/uv/) and retry
missing executable 'npx' — install Node.js (https://nodejs.org) and retry
```

Fix:

```powershell
# uv (Python-based MCP servers)
pip install uv            # or: irm https://astral.sh/uv/install.ps1 | iex

# Node.js (npx-based MCP servers) — https://nodejs.org
node --version
npx --version
```

Then restart Elidia (MCP connections are established at startup).

### See the real error

Every stdio MCP subprocess's stderr is captured to a shared per-profile log:

```
~/.elidia/logs/mcp-stderr.log        # Windows: %USERPROFILE%\.elidia\logs\mcp-stderr.log
```

Tail it while reconnecting the server to see the exact process error.

---

## "Skill '<name>' not found"

Bundled skills (including `elidia-agent`) ship with the package and are seeded
into `~/.elidia/skills/` on first launch. If a bundled skill is missing on a
fresh install, the package itself did not ship its skill data — this was a
packaging bug in earlier releases where the wheel dropped the `skills`,
`optional-skills`, and `optional-mcps` directories.

Fix:

1. Upgrade to a current release and re-run once:

   ```powershell
   elidia update
   elidia doctor          # verify the bundled skills resolve
   ```

2. If you are on a package-manager build, confirm the skill files exist under
   the install's data directories (or set `ELIDIA_BUNDLED_SKILLS` /
   `ELIDIA_OPTIONAL_SKILLS` to the correct locations — see
   [Environment Variables](environment-variables.md)).

---

## File search: "requires 'rg' or 'find'"

Elidia's file-search tool now has a built-in pure-Python fallback on **local**
backends, so `ripgrep` (`rg`) and `find`/`grep` are no longer hard
prerequisites for search. The `install.ps1` installer still installs `ripgrep`
for speed; nothing to do here unless you explicitly disabled the fallback.

---

## Permissions

The correct posture is to **run Elidia as the same user that owns the project
files** — then no extra grants are needed. Only deviate from that when you must
run the agent as a different account.

### Do

- Run the agent under your own account, in your own project directory.
- If a service account must access a specific tree, grant **only that account**
  the narrowest right it needs:

  ```powershell
  # Grant one specific user Modify access (inherited) to one tree — not "Users"
  icacls "F:\workspace" /grant "DOMAIN\agent-user:(OI)(CI)M"
  ```

- Fix **ownership** first when a tree has been taken over by another account,
  rather than layering broad grants on top.

### Do not

- Never grant full control to `Everyone` or the built-in `Users` group:

  ```powershell
  # ❌ INSEGURE — gives every local account full control of every project
  icacls "F:\workspace" /grant Users:F
  icacls "F:\workspace" /grant *S-1-1-0:F
  ```

  A blanket `Users:F` grant exposes every project in that tree to every local
  user and service on the machine. The narrow, single-account grant above is
  always preferred.

---

## Environment variables that matter

| Variable | Default | Purpose |
|---|---|---|
| `ELIDIA_HOME` | `~/.elidia` (`%USERPROFILE%\.elidia` on Windows) | Root data directory (config, skills, sessions, logs) |
| `ELIDIA_GIT_BASH_PATH` | auto-detected | Overrides the `bash.exe` used by the terminal tool on Windows |
| `ELIDIA_BUNDLED_SKILLS` | packaged `skills/` dir | Overrides where bundled skills are read from |
| `ELIDIA_OPTIONAL_SKILLS` | packaged `optional-skills/` dir | Overrides the optional-skills directory |
| `ELIDIA_OPTIONAL_MCPS` | packaged `optional-mcps/` dir | Overrides the optional-MCP catalog directory |

Set them in `~/.elidia/.env` or your shell profile. See
[Environment Variables](environment-variables.md) for the complete reference.

---

## `elidia doctor`

`elidia doctor` is the fastest way to localize a problem. It reports:

- the detected install method (pip / git / Homebrew / Nix) and layout
- missing prerequisites (bash, uv, Node, ripgrep, …)
- whether bundled skills and the MCP catalog resolve
- config health

Run it before opening an issue, and paste its output into the report.

---

## macOS / Linux

Native Unix hosts already ship `bash`, so the Windows-specific shell and WSL
issues above do not apply. The same guidance still holds for:

- **MCP "failed"** — check for a missing `uvx`/`npx`/`node`, and read
  `~/.elidia/logs/mcp-stderr.log` for the real error.
- **MCP "disabled"** — set `enabled: true` or install the catalog entry
  (`elidia mcp install <name>`).
- **Missing bundled skills** — upgrade (`elidia update`) or check
  `ELIDIA_BUNDLED_SKILLS`; run `elidia doctor`.
- **File search** — the built-in Python fallback applies on local backends, so
  `rg`/`find` are optional.
- **Permissions** — same rule: run as the file owner; grant specific users, not
  `Everyone`; avoid `chmod -R 777` (the Unix equivalent of the blanket grant).

For macOS/Linux installation details, see [Installation](installation.md).
