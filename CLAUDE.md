# CLAUDE.md — SysControl Project Guide

## What is SysControl?

An AI agent for macOS that answers questions about your system using 59+ MCP tools. Three interfaces share the same backend: native SwiftUI app, CLI, and Claude Desktop (MCP server).

**Repo:** `ks6573/SysControl` on GitHub.

---

## Architecture

```
agent.py               ← CLI entry shim → agent.cli:main()
mcp/server.py          ← MCP server (~4650 lines, all 59+ tools, JSON-RPC over stdio)
mcp/prompt.json        ← System prompt injected into all LLM requests
agent/core.py          ← Shared: MCPClient, MCPClientPool, run_streaming_turn(), TurnCallbacks
agent/bridge.py        ← JSON-over-stdio bridge for the Swift frontend
agent/cli.py           ← Interactive terminal agent
scripts/make_icon.py   ← Generates .icns app icon from source image
swift/                 ← Native SwiftUI macOS app (macOS 14+)
  SysControl/
    App/               ← SysControlApp.swift (entry), AppState.swift (central @Observable)
    Services/          ← BackendService.swift (bridge IPC), UpdateService.swift
    Views/             ← SwiftUI views (Chat, Sidebar, Settings, InputBar, etc.)
    Models/            ← ChatMessage, ChatSession, ProviderConfiguration, SavedChat
    Storage/           ← PersistenceManager, ChatHistoryManager, ProviderConfigStore
  Package.swift        ← SPM manifest — explicit source list, must be updated when adding files
  build.sh             ← Builds .app bundle + optional .dmg (reads VERSION → Info.plist)
  install.sh           ← One-liner installer: clone, build, install to /Applications
VERSION                ← Single source of truth for app version
```

### Key data flows

- **Swift app → Python:** `BackendService` spawns `agent/bridge.py` via `Process()`, JSON-over-stdio IPC
- **Bridge → MCP:** `agent/core.py` MCPClient connects to `mcp/server.py` via JSON-RPC over stdio
- **Streaming loop:** `run_streaming_turn()` in `core.py` handles the LLM ↔ tool-call loop with `TurnCallbacks` for UI events

### MCP protocol

JSON-RPC 2.0 over stdio. Supported methods: `initialize`, `tools/list`, `tools/call`, `ping`. Notifications (no `id`) are acknowledged silently. Error codes: `-32700` (parse), `-32601` (method not found), `-32603` (internal). Tools are registered in the `TOOLS` dict at line ~3677 of `server.py` with keys: `description`, `parallel`, `inputSchema`, `fn`.

---

## LLM Providers

| Provider | Base URL | Default Model | API Key |
|---|---|---|---|
| Local (Ollama) | `http://localhost:11434/v1` | `qwen3:30b` | `"ollama"` (dummy) |
| Cloud (Ollama Cloud) | `https://ollama.com/v1` | `gpt-oss:120b` | Required |

Constants in `agent/core.py` lines 66–71. Configurable via CLI flags (`--provider`, `--model`, `--api-key`), Swift Settings UI, or env vars for the bridge (`SYSCONTROL_API_KEY`, `SYSCONTROL_BASE_URL`, `SYSCONTROL_MODEL`).

---

## Coding Standards

Established through 5 rounds of NASA-style code reviews:

1. **PEP 8** — strict compliance for all Python
2. **Function complexity** — max 60 lines; extract helpers when approaching limit
3. **Type safety** — explicit annotations; `collections.abc.Callable` not `typing.Callable`; minimize `type: ignore`
4. **Defensive programming** — sanitize at boundaries: `_escape_applescript()`, NSPredicate escaping, regex validation for journalctl
5. **NASA Power of 10** — bounded loops (`MAX_TOOL_ROUNDS = 15`), no recursion, minimal globals
6. **Documentation** — docstrings on all public functions and modules

### Python specifics

- Thread safety: `threading.Lock`, double-checked locking (see `_CONFIG_LOCK`, `_NVML_LOCK`)
- `RESPONSE_STYLE_GUIDANCE` defined once in `core.py` — import, don't duplicate
- Error classes in cli.py: `_LLMError`, `_ToolError`, `_MCPError`
- Streaming errors are categorized: Timeout, Connection, Auth, API, MCP, Tool, Loop

### Swift specifics

- **Package.swift has an explicit `sources:` list** — MUST add new `.swift` files or build fails
- macOS 14+ minimum (`.macOS(.v14)`)
- `@Observable` pattern (not `ObservableObject`/`@Published`)
- `AppState` is central state, passed via `.environment(appState)`

---

## Two User Populations

- **DMG-installed:** Downloaded from GitHub Releases, no git repo. Updates = download new DMG.
- **Source-installed:** Cloned to `~/.syscontrol/build/`, has `.git`. Updates = `syscontrol-update` or in-app auto-update.

Detection: `~/.syscontrol/build/.git` exists → source install.

---

## Memory System

- File: `~/.syscontrol/SysControl_Memory.md` — append-only, timestamped notes
- MCP tools: `read_memory` (reads file), `append_memory_note` (appends with timestamp, thread-safe via `_MEMORY_LOCK`)
- CLI exit: `offer_memory_save()` prompts user to save a session note
- Loading: `load_memory()` in `core.py` — if file exists, system prompt includes memory guidance

---

## Common Tasks

### Adding a new MCP tool
1. Add the tool function to `mcp/server.py`
2. Register in the `TOOLS` dict (same file) with `description`, `parallel`, `inputSchema`, `fn`
3. Update tool count in `README.md` if changed

### Adding a new Swift file
1. Create file under `swift/SysControl/`
2. **Add to `swift/Package.swift` `sources:` array**
3. Verify: `cd swift && swift build`

### Building
```bash
cd swift && swift build              # debug
cd swift && ./build.sh release       # release .app + .dmg
uv run agent.py                      # CLI
```

### Releasing
1. Update `VERSION` file
2. Push a `v*` tag (e.g., `git tag v1.1.0 && git push origin v1.1.0`)
3. GitHub Actions builds DMG and creates release automatically

### Code quality
```bash
ruff check .                         # lint (E, W, F, I, UP, B, SIM)
mypy agent/ mcp/                     # type check (python 3.11)
pytest                               # tests (testpaths = ["tests"])
```

---

## Permissions

Sensitive tools disabled by default. Enabled via `~/.syscontrol/config.json`:

`allow_shell`, `allow_messaging`, `allow_message_history`, `allow_screenshot`, `allow_file_read`, `allow_file_write`, `allow_calendar`, `allow_contacts`, `allow_accessibility`, `allow_tool_creation`

---

## File Size Reference

Read specific sections, not entire files:

| File | ~Lines | Notes |
|---|---|---|
| `mcp/server.py` | ~4650 | All MCP tools — largest file |
| `agent/core.py` | ~764 | Shared agent infrastructure |
| `agent/cli.py` | ~599 | CLI interface |

---

## Config & Runtime Paths

| Path | Purpose |
|---|---|
| `~/.syscontrol/config.json` | Permission flags |
| `~/.syscontrol/chat_history/` | Auto-saved markdown conversations |
| `~/.syscontrol/SysControl_Memory.md` | Persistent session notes |
| `~/.syscontrol/reminders.json` | Reminder entries |
| `~/.syscontrol/build/` | Source-install clone directory |
| `~/.syscontrol/remote_config.json` | Telegram/WhatsApp/Messenger tokens |
| `VERSION` (repo root) | App version, read by `build.sh` |
| `.github/workflows/release.yml` | Builds DMG on `v*` tag push |
| `pyproject.toml` | Python deps, scripts, linting config |

### pyproject.toml scripts
```
syscontrol        → agent.cli:main
syscontrol-server → mcp.server:main
```

### Python dependencies
Core: `psutil`, `matplotlib`, `openai`. Optional groups: `gpu` (nvidia-ml-py), `dev` (ruff, mypy, pytest).
