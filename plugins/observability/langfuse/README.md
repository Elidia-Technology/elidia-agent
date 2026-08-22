# Langfuse Observability Plugin

This plugin ships bundled with Elidia but is **opt-in** — it only loads when
you explicitly enable it.

## Enable

Pick one:

```bash
# Interactive: walks you through credentials + SDK install + enable
elidia tools  # → Langfuse Observability

# Manual
pip install langfuse
elidia plugins enable observability/langfuse
```

## Required credentials

Set these in `~/.elidia/.env` (or via `elidia tools`):

```bash
ELIDIA_LANGFUSE_PUBLIC_KEY=pk-lf-...
ELIDIA_LANGFUSE_SECRET_KEY=sk-lf-...
ELIDIA_LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

Without the SDK or credentials the hooks no-op silently — the plugin fails
open.

## Verify

```bash
elidia plugins list                 # observability/langfuse should show "enabled"
elidia chat -q "hello"              # then check Langfuse for a "Elidia turn" trace
```

## Optional tuning

```bash
ELIDIA_LANGFUSE_ENV=production       # environment tag
ELIDIA_LANGFUSE_RELEASE=v1.0.0       # release tag
ELIDIA_LANGFUSE_SAMPLE_RATE=0.5      # sample 50% of traces
ELIDIA_LANGFUSE_MAX_CHARS=12000      # max chars per field (default: 12000)
ELIDIA_LANGFUSE_DEBUG=true           # verbose plugin logging
```

## Disable

```bash
elidia plugins disable observability/langfuse
```
