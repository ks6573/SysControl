# CLAUDE.md — SysControl Project Guide

## What is SysControl?

An AI agent for macOS that answers questions about your system using 85 MCP tools. Three interfaces share the same backend: native SwiftUI app, CLI, and Claude Desktop (MCP server).

**Repo:** `ks6573/SysControl` on GitHub.

---

## Architecture

```
agent.py               ← CLI entry shim → agent.cli:main()
mcp/server.py          ← MCP server (~6800 lines, all 85 tools, JSON-RPC over stdio)
mcp/prompt.json        ← System prompt injected into all LLM requests
agent/core.py          ← Shared: MCPClient, MCPClientPool, run_streaming_turn(), TurnCallbacks
agent/bridge.py        ← JSON-over-stdio bridge for the Swift frontend
agent/cli.py           ← Interactive terminal agent
agent/agents.py        ← Sub-agent specs: AgentSpec, AgentRegistry, built-in agents
agent/runner.py        ← Sub-agent runner: run_subagent() with isolated context + filtered tools
deep_research/         ← Deep research agent: iterative web research with claim verification
scripts/make_icon.py   ← Generates .icns app icon from source image
swift/                 ← Native SwiftUI macOS app (macOS 14+)
  SysControl/
    App/               ← SysControlApp.swift (entry), AppState.swift (central @Observable)
    Services/          ← BackendService.swift (bridge IPC), UpdateService.swift
    Views/             ← SwiftUI views (Chat, Sidebar, Settings, InputBar, etc.)
    Models/            ← ChatMessage, ChatSession, ProviderConfiguration, SavedChat
    Storage/           ← PersistenceManager, ChatHistoryManager, ProviderConfigStore, PermissionConfigStore
  Package.swift        ← SPM manifest — explicit source list, must be updated when adding files
  build.sh             ← Builds .app bundle + optional .dmg (reads VERSION → Info.plist)
  install.sh           ← One-liner installer: clone, build, install to /Applications
VERSION                ← Single source of truth for app version
```

### Key data flows

- **Swift app → Python:** `BackendService` spawns `agent/bridge.py` via `Process()`, JSON-over-stdio IPC
- **Bridge → MCP:** `agent/core.py` MCPClient connects to `mcp/server.py` via JSON-RPC over stdio
- **Streaming loop:** `run_streaming_turn()` in `core.py` handles the LLM ↔ tool-call loop with `TurnCallbacks` for UI events
- **Chart images:** MCP tools return `(data, base64_png)` tuples → `call_tool()` saves PNG to temp file → bridge emits `chart_image` event → Swift renders inline via `ChartImageView`
- **Deep research:** `deep_research` MCP tool → `deep_research/orchestrator.py` creates its own OpenAI client from env vars, runs iterative plan→search→extract→verify→synthesize loop using existing `web_search()` / `web_fetch()` functions
- **Sub-agents:** `run_agent` MCP tool → `agent/runner.py:run_subagent()` spawns an isolated MCPClient subprocess (with `SYSCONTROL_AGENT_DEPTH=1` to block nesting), filters tools to the spec's allowlist, and calls `run_streaming_turn()` with a fresh message history. `agent/agents.py` holds `AgentSpec` definitions and the `AgentRegistry`.

### Bridge protocol events (bridge → Swift)

| Event | Fields | Purpose |
|---|---|---|
| `ready` | `tool_count`, `model` | Backend initialized |
| `configured` | `model` | Provider reconfigured |
| `token` | `text` | Streaming LLM token |
| `tool_started` | `names` | Tool execution began |
| `tool_finished` | `name` | Tool execution done |
| `chart_image` | `path` | Chart PNG saved to temp file |
| `turn_done` | `finish_reason`, `elapsed` | LLM turn complete |
| `error` | `category`, `message` | Categorized error |

### MCP protocol

JSON-RPC 2.0 over stdio. Supported methods: `initialize`, `tools/list`, `tools/call`, `ping`. Notifications (no `id`) are acknowledged silently. Error codes: `-32700` (parse), `-32601` (method not found), `-32603` (internal). Tools are registered in the `TOOLS` dict at line ~3677 of `server.py` with keys: `description`, `parallel`, `inputSchema`, `fn`.

When a tool returns a `(data_dict, base64_png)` tuple, the MCP response contains two content items: `{"type": "text", ...}` and `{"type": "image", "data": ..., "mimeType": "image/png"}`. `MCPClient.call_tool()` extracts both, saves images to `/tmp/syscontrol_chart_*.png`, and appends `[chart_image:/path]` markers to the text result.

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
- Tables use SwiftUI `Grid` (not `HStack`) for proper column alignment — see `MarkdownTableView` in `LazyMarkdownText.swift`
- Chart images rendered via `ChartImageView` in `MessageBubble.swift` using `NSImage(contentsOfFile:)`

---

## Two User Populations

- **DMG-installed:** Downloaded from GitHub Releases, no git repo. Updates = download new DMG.
- **Source-installed:** Cloned to `~/.syscontrol/build/`, has `.git`. Updates = `syscontrol-update` or in-app auto-update.

Detection: `~/.syscontrol/build/.git` exists → source install.

### DMG build: relocatable venv

`build.sh` copies `.venv` into the `.app` bundle and makes it relocatable:
1. Replaces symlinked `python3` with the real binary (copied from the build machine)
2. Copies Python stdlib into the venv (uv keeps it external)
3. Patches `pyvenv.cfg` to point at the bundled `bin/`
4. Validates imports (`psutil`, `openai`) at build time

`BackendService.swift` uses `isExecutableFile(atPath:)` to detect broken venvs and falls back to `/usr/bin/python3`. It also captures stderr to surface `ImportError`/`ModuleNotFoundError` to the UI.

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
3. Update tool count in `README.md` and `CLAUDE.md` if changed
4. For chart tools: return `(data_dict, base64_png)` tuple, use `_style_chart_dark()` + `_fig_to_b64()` helpers
5. For document tools: gate with `allow_file_read` / `allow_file_write`; use `openpyxl` (xlsx), `python-docx` (docx), `pypdf` (pdf), or stdlib `csv`

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
2. Commit and push to master
3. Push a `v*` tag (e.g., `git tag v1.1.0 && git push origin v1.1.0`)
4. GitHub Actions builds DMG and creates release automatically

**Note:** `softprops/action-gh-release` has no v3 — use `@v2`. `actions/checkout@v5` is current.

### Code quality
```bash
ruff check .                         # lint (E, W, F, I, UP, B, SIM)
mypy agent/ mcp/ deep_research/       # type check (python 3.11)
pytest                               # tests (testpaths = ["tests"])
```

---

## Permissions

Sensitive tools disabled by default. Enabled via `~/.syscontrol/config.json`:

`allow_shell`, `allow_messaging`, `allow_message_history`, `allow_screenshot`, `allow_file_read`, `allow_file_write`, `allow_calendar`, `allow_contacts`, `allow_accessibility`, `allow_tool_creation`, `allow_deep_research`, `allow_email`, `allow_notes`, `allow_brew`, `allow_agents`

---

## File Size Reference

Read specific sections, not entire files:

| File | ~Lines | Notes |
|---|---|---|
| `mcp/server.py` | ~6800 | All MCP tools — largest file |
| `agent/core.py` | ~770 | Shared agent infrastructure |
| `agent/cli.py` | ~599 | CLI interface |
| `agent/agents.py` | ~160 | AgentSpec, AgentRegistry, 4 built-in agents |
| `agent/runner.py` | ~120 | run_subagent() — isolated sub-agent execution |
| `deep_research/` | ~800 | 12 modules — orchestrator, schemas, LLM steps, retriever, evidence store |

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
Core: `psutil`, `matplotlib`, `openai`, `openpyxl`, `python-docx`, `pypdf`. Optional groups: `gpu` (nvidia-ml-py), `dev` (ruff, mypy, pytest).
