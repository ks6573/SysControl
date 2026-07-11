# CLAUDE.md — SysControl Project Guide

## What is SysControl?

An AI agent for macOS and Windows 11 that answers questions about your system using 116 MCP tools. Four interfaces share the same Python backend: native SwiftUI app (macOS), Flet desktop app (Windows, `flet_app/`), CLI (cross-platform), and Claude Desktop (MCP server).

**Repo:** `ks6573/SysControl` on GitHub.

**Cross-platform:** the Python backend (`agent/`, `mcp/`, `deep_research/`, `flet_app/`) and the CLI run on macOS, Windows, and Linux. `mcp/server.py` branches on `IS_MACOS`/`IS_LINUX`/`IS_WIN` (see the `get_startup_items()` dispatcher pattern); macOS-only tools (AppleScript: iMessage/Mail/Calendar/Contacts/Notes, Homebrew, Time Machine) return a clean "not supported" dict off macOS rather than failing. The SwiftUI app is macOS-only; the Flet app is the Windows GUI (both drive the same backend).

---

## Architecture

```
agent.py               ← CLI entry shim → agent.cli:main()
mcp/server.py          ← MCP server (~9200 lines, all 116 built-in tools, JSON-RPC over stdio)
mcp/connectors.py      ← External stdio MCP manager; minimal env + namespaced tool routing
mcp/tool_capabilities.py ← Platform, permission, category, and risk metadata for every tool
mcp/prompt.json        ← System prompt injected into all LLM requests
agent/core.py          ← Shared: MCPClient, MCPClientPool, run_streaming_turn(), TurnCallbacks
agent/bridge.py        ← JSON-over-stdio bridge for the Swift frontend
agent/cli.py           ← Interactive terminal agent (prompt_toolkit REPL, slash registry, /show, /init, /compact, --continue/--resume)
agent/cli_keys.py      ← KeyBindings (Enter/Ctrl-D submit semantics) + SIGINT install_sigint_handler context manager
agent/cli_completers.py← _SlashCompleter merge target + AtFileCompleter; submit-time @file expansion
agent/cli_session.py   ← Atomic JSON session store at ~/.syscontrol/cli_sessions/
agent/cli_compact.py   ← Synchronous /compact summarization with undo snapshot
agent/credentials.py   ← Native Keychain/Credential Manager storage with protected-file fallback
agent/automations.py   ← Persistent bounded scheduler + run history for read-only tool automations
agent/audit.py         ← Privacy-preserving JSONL audit log (argument names, never values)
agent/updater.py       ← `syscontrol --update` / `/update` self-update via uv tool install
agent/slash.py         ← SlashCommand dataclass + SlashRegistry consumed by cli.py
agent/agents.py        ← Sub-agent specs: AgentSpec, AgentRegistry, 5 built-in agents
agent/runner.py        ← Sub-agent runner: run_subagent() with isolated context + filtered tools
deep_research/         ← Deep research agent: iterative web research with claim verification
flet_app/              ← Native Windows desktop GUI (Flet, Python) — Windows counterpart to swift/
  main.py              ← Entry + frozen-bundle argv sentinel (--run-mcp-server / --selftest)
  app.py, controller.py← Page assembly + central orchestration; runs the backend in-process
  backend.py           ← run_streaming_turn() on a worker thread (no subprocess bridge needed)
  callbacks via controller; views/ (chat, sidebar, settings, onboarding), store/ (~/.syscontrol JSON)
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
- **CLI coding mode:** `agent/cli.py --coding --approval {plan,standard,nuke}` narrows tools to code/file/git/shell capabilities and installs a tool-approval hook on `MCPClientPool`
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

`build.sh` builds the bundled venv from a **uv-managed standalone CPython**
(`astral-sh/python-build-standalone`), NOT framework Python. Framework Python
(Homebrew/python.org) is not relocatable — its `bin/python3` launcher loads the
interpreter from a framework dylib by absolute path (e.g.
`/opt/homebrew/Cellar/python@3.14/3.14.4/.../Python`), so a copied bundle only
runs where that exact path exists and dies with `dyld: Library not loaded` on
any other Mac (or after `brew upgrade` bumps the patch version). Standalone
CPython resolves `libpython` via `@rpath = @executable_path/../lib` and its
C-extensions carry no external absolute paths, so it relocates by plain copy.

Steps (gated on `uv` being present; `SYSCONTROL_BUNDLE_PYTHON` overrides version, default 3.14):
1. `uv python install` + `uv venv --managed-python`, then `uv pip install -r pyproject.toml`
2. Replace the venv's symlinked `python3` with the real standalone binary
3. **Copy `libpython*.dylib` into the venv `lib/`** so the binary's `@rpath` resolves in-bundle (the key step)
4. Copy Python stdlib into the venv (uv keeps it external); patch `pyvenv.cfg` `home`
5. Ad-hoc sign all Mach-O (incl. the interpreter + dylib); validate `import ssl, psutil, openai` at build time (release builds abort on failure)

`BackendService.swift` chooses the interpreter via `interpreterRuns()` — it
*launches* the bundled python (not just `isExecutableFile`, which can't catch a
present-but-dyld-broken binary) and falls back to `/usr/bin/python3` only if it
won't run. `startupFailureMessage()` surfaces dyld/library failures and
`ImportError`/`ModuleNotFoundError` from the stderr ring buffer to the UI.

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
cd swift && swift build              # debug (macOS GUI)
cd swift && ./build.sh release       # release .app + .dmg (macOS)
uv run agent.py                      # CLI (any OS)
uv run syscontrol-gui                # Windows GUI, dev mode (any OS with a display)
uv run --extra gui --extra build pyinstaller SysControl.spec   # Windows .exe -> dist/SysControl/
```

### Windows packaging (`SysControl.spec`)
`flet_app/` is bundled by PyInstaller into a one-folder `dist/SysControl/` (zipped
for release as `SysControl-windows-x64.zip`). The frozen `SysControl.exe` doubles as
the MCP server: `agent/core.py:MCPClient` spawns `server_spawn_cmd()` which, when
frozen (`agent/paths.py:IS_FROZEN`), re-execs the exe with `--run-mcp-server`;
`flet_app/main.py` intercepts that sentinel and runs `mcp.server.main()` before
importing Flet. `SysControl.spec` collects Flet's Flutter client, matplotlib (Agg
fonts), certifi (TLS), `mcp/prompt.json`, and `agent/skills_builtin`, and lists
`mcp.server` as a hidden import. `--selftest` validates deps in CI.

### Adding a new Flet GUI file
Just create it under `flet_app/` and import it — there's no explicit sources list
(unlike `swift/Package.swift`). The GUI uses Flet 0.85 APIs (`ft.run`, `ft.Colors`,
`ft.Padding`/`ft.Border`/`ft.Margin`, `ft.BoxFit`, `page.show_dialog`/`pop_dialog`,
`page.run_thread` for thread→UI marshaling).

### Releasing
1. Update `VERSION` file
2. Commit and push to master
3. Push a `v*` tag (e.g., `git tag v1.1.0 && git push origin v1.1.0`)
4. GitHub Actions builds DMG and creates release automatically

**Note:** Pinned actions: `softprops/action-gh-release@v3` and `actions/checkout@v6` (both on the Node 24 runtime). `release.yml` does not pre-sync the dev venv — `build.sh` provisions and validates its own relocatable standalone CPython for the bundle.

### Code quality
```bash
ruff check .                         # lint (E, W, F, I, UP, B, SIM)
mypy agent/ mcp/ deep_research/       # type check (python 3.11)
pytest                               # tests (testpaths = ["tests"])
```

---

## Permissions

Sensitive tools disabled by default. Enabled via `~/.syscontrol/config.json`:

`allow_shell`, `allow_messaging`, `allow_message_history`, `allow_screenshot`, `allow_file_read`, `allow_file_write`, `allow_calendar`, `allow_contacts`, `allow_accessibility`, `allow_tool_creation`, `allow_deep_research`, `allow_email`, `allow_notes`, `allow_brew`, `allow_agents`, `allow_clipboard`

---

## File Size Reference

Read specific sections, not entire files:

| File | ~Lines | Notes |
|---|---|---|
| `mcp/server.py` | ~7400 | All MCP tools — largest file |
| `agent/core.py` | ~770 | Shared agent infrastructure |
| `agent/cli.py` | ~599 | CLI interface |
| `agent/agents.py` | ~210 | AgentSpec, AgentRegistry, 5 built-in agents (explorer, analyst, researcher, writer, coder) |
| `agent/runner.py` | ~120 | run_subagent() — isolated sub-agent execution |
| `deep_research/` | ~800 | 12 modules — orchestrator, schemas, LLM steps, retriever, evidence store |

---

## Config & Runtime Paths

| Path | Purpose |
|---|---|
| `~/.syscontrol/config.json` | Permission flags |
| `~/.syscontrol/chat_history/` | Auto-saved markdown conversations (Swift app) |
| `~/.syscontrol/cli_sessions/` | Auto-saved JSON conversations (CLI; consumed by `--continue`/`--resume`) |
| `~/.syscontrol/cli_history` | prompt_toolkit readline-style input history |
| `~/.syscontrol/cli_credentials.json` | Cached Ollama Cloud API key (0600, opt-out via `--no-save-key` or `/logout`) |
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
