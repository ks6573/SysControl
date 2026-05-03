# SysControl

An AI agent for your Mac that answers questions about your system — and can extend itself with new tools on the fly.

92 real-time tools covering CPU, RAM, GPU, disk, network, processes, iMessage, email, clipboard, browser, weather, reminders, Docker, Time Machine, Wi-Fi, calendar, contacts, Notes, Homebrew, media control, file management, Spotlight search, spreadsheets, Word documents, PDFs, image generation, deep web research, sub-agent orchestration, code editing, git integration, and more. The agent picks the right tools automatically, runs them in parallel, and answers in plain English.

Three ways to run it — pick whichever fits your workflow:

| | How | Best for |
|---|---|---|
| **App** | [Download the `.app`](#app-recommended) | One-click native macOS experience — no setup required |
| **CLI** | `syscontrol` ([one-line install](#cli)) | Terminal-first workflow, scripting, SSH sessions |
| **Claude Desktop** | MCP server | Using SysControl tools inside Claude Desktop |

All interfaces share the same agent, tools, and providers — they're interchangeable.

---

## App (Recommended)

A native SwiftUI app with streaming chat, Markdown rendering, chat history sidebar, and auto-save — no Python, no terminal, no dependencies to install. Just download, open, and configure your provider in Settings.

### Download

**Option A — Pre-built DMG** (no Xcode required):

Download the latest `SysControl.dmg` from [GitHub Releases](https://github.com/ks6573/SysControl/releases), drag to Applications, then bypass Gatekeeper on first launch (the app is ad-hoc signed, not notarized):

```bash
xattr -r -d com.apple.quarantine /Applications/SysControl.app
```

Or right-click the app → **Open** → **Open** the first time.

**Option B — Install from source** (compiles locally, bypasses Gatekeeper automatically):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/ks6573/SysControl/master/swift/install.sh)"
```

To update later: use **Check for Updates** in the app (⇧⌘U), or run `syscontrol-update` from Terminal.

To uninstall: re-run with `--uninstall`.

**Option C — Build manually:**

```bash
git clone https://github.com/ks6573/SysControl.git
cd SysControl/swift
./build.sh release
open .build/SysControl.app
```

> **Requires:** macOS 14 (Sonoma) or later. Options B and C also require Xcode Command Line Tools (`xcode-select --install`).

### Features

- **Streaming responses** — tokens appear as they arrive with live Markdown rendering
- **Auto-save** — every conversation is saved automatically with an LLM-generated title
- **Chat history sidebar** — browse and delete past chats
- **Settings** — switch between local (Ollama) and cloud providers in-app
- **In-app updates** — check for new versions from the menu bar (⇧⌘U) or Settings; DMG users get a one-click download, source-install users update automatically
- **No setup** — everything is configured through the app itself

### First Launch

On first launch an onboarding sheet appears automatically:

1. Choose **Local (Ollama)** — requires [Ollama](https://ollama.com) running locally, no API key needed
2. Or choose **Cloud** — enter your API key
3. Click **Done** and start chatting

To change providers later, open **Settings** (⌘,).

> Chat history is saved as Markdown in `~/.syscontrol/chat_history/` — view, edit, or delete freely.

---

## CLI

A terminal agent that runs the same backend as the app. Two install paths:

**Option A — One-line install (recommended):**

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/ks6573/SysControl/master/install-cli.sh)"
```

Installs `uv` if missing, then runs `uv tool install` against the GitHub repo, exposing `syscontrol` and `syscontrol-server` on your `PATH` in an isolated venv. No clone required.

To update later: `syscontrol-cli-update`

To uninstall: re-run with `-- --uninstall`.

**Option B — From a clone (for development):**

```bash
git clone https://github.com/ks6573/SysControl.git
cd SysControl
curl -LsSf https://astral.sh/uv/install.sh | sh   # if uv not installed
uv sync
uv run agent.py
```

### Requirements

- macOS or Linux
- Python **3.11+** (uv will fetch one if your system Python is older)
- [Ollama](https://ollama.com) for local mode, **or** an Ollama Cloud API key for cloud mode

### CLI Flags

```bash
syscontrol                                          # interactive
syscontrol --provider local --model qwen3:30b      # local, skip prompt
syscontrol --provider cloud --api-key sk-...       # cloud, skip prompt
syscontrol --coding --approval standard            # coding agent, ask before edits/shell
syscontrol --coding --approval plan                # read-only planning mode
syscontrol --coding --approval nuke                # auto-accept coding edits/shell
```

> Cloned (Option B) users can substitute `uv run agent.py` for `syscontrol` in any of the commands below.

### Coding Mode

The CLI can run as a coding agent with a narrowed code tool set: file search/read/edit,
git status/diff, and shell commands. Approval modes:

| Mode | Behavior |
|---|---|
| `plan` | Read-only. The agent can inspect and produce an implementation plan, but edits and shell commands are blocked. |
| `standard` | Reads are automatic; file writes and shell commands ask for approval in the terminal. |
| `nuke` | Auto-accepts coding edits and shell commands for the session. |

Inside coding mode, use `/approval plan`, `/approval standard`, or `/approval nuke` to switch policies.

### Slash Commands & Keyboard Shortcuts

The interactive CLI supports a built-in slash menu (type `/` to pop the completion list) and standard editor key bindings.

| Command | Description |
|---|---|
| `/help` | Show all commands and keyboard shortcuts |
| `/clear` | Clear the screen |
| `/reset` | Clear conversation history (keeps system prompt) |
| `/tools [filter]` | List available tools, optionally filtered by substring |
| `/model` | Show the active model and provider |
| `/memory <note>` | Append a timestamped note to `SysControl_Memory.md` |
| `/approval plan\|standard\|nuke` | Switch coding-mode approval policy (coding mode only) |
| `/exit` | Quit the session |

| Key | Action |
|---|---|
| `↑` / `↓` | History navigation |
| `Ctrl+R` | Reverse history search |
| `Tab` | Complete the current slash command or argument |
| `Ctrl+L` | Clear the screen |
| `Esc, Enter` | Insert newline (multi-line input) |
| `Ctrl+D` | Exit the session |

History is persisted to `~/.syscontrol/cli_history` and survives restarts.

### Local Mode (Ollama)

```bash
ollama pull qwen3:30b   # recommended
ollama serve
syscontrol --provider local
```

**Tool-calling capable models:**

| Model | Notes |
|---|---|
| `qwen3:30b` | Default. Best tool use and reasoning |
| `qwen3:8b` | Faster, lower memory — includes thinking mode |
| `qwen2.5:7b` | Lightweight alternative |
| `llama3.1:8b` | Battle-tested fallback |

> Models without native tool-calling (e.g. `gemma3`) will error.

### Cloud Mode (Ollama Cloud)

```bash
syscontrol --provider cloud
# Enter your key when prompted — not echoed or stored in shell history
```

Get a key at [ollama.com/settings/keys](https://ollama.com/settings/keys). Default cloud model: `gpt-oss:120b`.

### Ending a Session

Say any natural goodbye (`bye`, `exit`, `quit`, `done`, `farewell`, `cya`, `goodnight`, …) or press **Ctrl-C**. The agent will offer to save your session before exiting.

### Session Memory

On exit you are prompted to save a short note about the session. Notes are appended to `SysControl_Memory.md` with a timestamp. On next startup, if the file exists its contents are injected into the system prompt so the agent has context from prior sessions. The file is append-only and plain text — edit or delete entries freely.

The agent can also save and recall memory mid-session via the `read_memory` and `append_memory_note` tools — no need to wait for exit.

> **Privacy:** SysControl stores only what you explicitly save. Ollama processes queries locally by default.

---

## Permissions & Security

Sensitive tools are **disabled by default**. Enable them in `~/.syscontrol/config.json`:

```json
{
  "allow_shell":           true,
  "allow_messaging":       true,
  "allow_message_history": true,
  "allow_screenshot":      true,
  "allow_file_read":       true,
  "allow_file_write":      true,
  "allow_calendar":        true,
  "allow_contacts":        true,
  "allow_accessibility":   true,
  "allow_tool_creation":   true,
  "allow_deep_research":   true,
  "allow_email":           true,
  "allow_notes":           true,
  "allow_brew":            true,
  "allow_agents":          true
}
```

Each disabled tool returns an error with the exact flag needed to enable it.

---

## Claude Desktop Setup

**1. Add the MCP server to your config**

| Platform | Config path |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "system-monitor": {
      "command": "/path/to/uv",
      "args": ["run", "/absolute/path/to/SysControl/mcp/server.py"],
      "env": {}
    }
  }
}
```

Use `which uv` to get the uv path.

**2. Set the system prompt** — create a Claude Desktop Project and paste the contents of `mcp/prompt.json` into the Project Instructions field.

**3. Restart Claude Desktop** — `system-monitor` will appear in the MCP servers list.

---

## Self-Extension

When you ask for something no tool covers, the agent offers to build it:

```
You: What song is playing in Spotify right now?

Agent: I don't have a tool for that. Want me to create one? (yes/no)

You: yes

Agent: ✓ Tool `get_spotify_track` installed. Restart and ask again.
```

The agent writes a Python function, validates syntax, scans for dangerous patterns (`eval`, `exec`, etc.), and appends it to `mcp/server.py`. Requires:

```json
{ "allow_tool_creation": true }
```

---

## Tools (92 total)

### Monitoring

| Tool | What it does |
|---|---|
| `get_cpu_usage` | CPU load (total + per-core), clock frequency, inline bar chart |
| `get_ram_usage` | RAM and swap — used, available, percent, inline stacked chart |
| `get_gpu_usage` | GPU load, VRAM, temperature per device (NVIDIA/pynvml), inline chart |
| `get_disk_usage` | Per-partition space and cumulative I/O counters |
| `get_network_usage` | Cumulative bytes sent/received and per-interface status |
| `get_realtime_io` | Live disk read/write and network download/upload speed (MB/s) |
| `get_top_processes` | Top N processes by CPU or memory |
| `get_full_snapshot` | Single call: CPU + RAM + GPU + disk + network + top processes |
| `get_system_alerts` | Triage scan returning prioritized critical/warning alerts |

### System & Hardware

| Tool | What it does |
|---|---|
| `get_device_specs` | Static profile: CPU model, core count, RAM, GPU VRAM, disks, OS |
| `get_battery_status` | Percent, charging state, time remaining |
| `get_temperature_sensors` | CPU/motherboard sensors (Linux/Windows) |
| `get_system_uptime` | Boot time, uptime, 1/5/15-min load averages |
| `get_hardware_profile` | Live pressure + specs + OC capability + upgrade feasibility + bottleneck analysis |

### Process Management

| Tool | What it does |
|---|---|
| `get_process_details` | Deep inspection of a PID: path, cmdline, user, RSS/VMS, threads, open files |
| `search_process` | Find processes by name (case-insensitive partial match) |
| `kill_process` | SIGTERM (default) or SIGKILL a PID. Refuses critical system processes. |

### Network & Connectivity

| Tool | What it does |
|---|---|
| `get_network_connections` | All active TCP/UDP connections with state and owning process |
| `network_latency_check` | Pings gateway, Cloudflare, Google DNS in parallel and diagnoses slowness |
| `get_wifi_networks` | Nearby networks with SSID, channel, security, signal strength |

### Storage

| Tool | What it does |
|---|---|
| `find_large_files` | Top N largest files under a path. Skips `.git`, `node_modules`, `.venv` |
| `eject_disk` | Unmount and eject an external disk by mountpoint |

### Messaging & Communication

| Tool | What it does |
|---|---|
| `send_imessage` | Send an iMessage or SMS via Messages.app. macOS only. |
| `get_imessage_history` | Read recent messages from `~/Library/Messages/chat.db`. macOS only. |
| `read_emails` | Read recent emails from Mail.app (by folder). Requires `allow_email`. macOS only. |
| `send_email` | Send an email via Mail.app. Requires `allow_email`. macOS only. |
| `search_emails` | Search emails across all accounts and mailboxes. Requires `allow_email`. macOS only. |

### Browser & Web

| Tool | What it does |
|---|---|
| `web_search` | DuckDuckGo search — title, URL, snippet. No API key. |
| `web_fetch` | Fetch a URL as plain text. No browser required. |
| `grant_browser_access` | Unlock browser control (called once, after user consent) |
| `browser_open_url` | Open a URL in the default browser |
| `browser_navigate` | Navigate the active tab via AppleScript (macOS) |
| `browser_get_page` | Return the URL, title, and text of the current tab (macOS) |

### Clipboard & Screen

| Tool | What it does |
|---|---|
| `get_clipboard` | Return current clipboard text |
| `set_clipboard` | Write text to the clipboard |
| `take_screenshot` | Full-screen PNG returned inline. Optionally save to file. macOS only. |
| `generate_image` | Generate an inline visual image artifact from a prompt. Requires an OpenAI image API key. |

### App Control & System

| Tool | What it does |
|---|---|
| `open_app` | Open an app by name (`open -a`). macOS only. |
| `quit_app` | Gracefully quit (AppleScript) or force-kill an app. macOS only. |
| `get_volume` | Output, input, and alert volume; mute state |
| `set_volume` | Set system output volume (0–100) |
| `get_now_playing` | Currently playing track in Music.app or Spotify (title, artist, album, position). macOS only. |
| `media_control` | Play, pause, skip, or stop Music.app / Spotify. Auto-detects active player. macOS only. |
| `get_frontmost_app` | Return the name of the focused application |
| `toggle_do_not_disturb` | Enable/disable Focus / DnD |
| `run_shortcut` | Run a named Shortcut via `shortcuts run`. macOS 12+. |

### File I/O & Shell

| Tool | What it does |
|---|---|
| `read_file` | Read a text file (up to 16,000 chars) |
| `write_file` | Write text to any path, creating directories as needed |
| `list_directory` | List directory contents with name, type, size, and modification time |
| `move_file` | Move or rename a file or directory |
| `copy_file` | Copy a file to a new location |
| `delete_file` | Delete a file or directory (Trash by default on macOS, recoverable) |
| `create_directory` | Create a directory and any missing parents |
| `search_files` | Search for files system-wide using macOS Spotlight (mdfind). Instant. macOS only. |
| `read_spreadsheet` | Read cells from `.xlsx` or `.csv` — supports sheet selection and cell ranges |
| `edit_spreadsheet` | Write cells (A1 notation) or append rows to `.xlsx` / `.csv`. Create new files. |
| `read_document` | Read paragraphs from `.docx`, `.txt`, or `.md` with word count |
| `edit_document` | Find/replace text, overwrite paragraphs, or append to `.docx` files |
| `read_pdf` | Extract text from PDF files, page by page (up to 200 pages) |
| `run_shell_command` | Execute a bash command and return stdout/stderr. **Disabled by default.** |

### Calendar, Contacts & Logs

| Tool | What it does |
|---|---|
| `get_calendar_events` | Upcoming events from Calendar.app for the next N days. macOS only. |
| `get_contact` | Search Contacts.app by name — phone and email. macOS only. |
| `list_notes` | List notes from Notes.app with title, folder, and timestamps. Requires `allow_notes`. |
| `read_note` | Read the full body of a note by title (partial match). Requires `allow_notes`. |
| `create_note` | Create a new note in Notes.app. Requires `allow_notes`. |
| `get_startup_items` | Auto-start items (macOS LaunchAgents, Windows Registry, Linux `.desktop`) |
| `tail_system_logs` | Last N lines of the system log with optional keyword filter |

### Utilities

| Tool | What it does |
|---|---|
| `set_reminder` | Schedule a macOS notification. Accepts `"in 2 hours"`, `"tomorrow at 9am"`, etc. |
| `list_reminders` | All pending reminders with IDs and fire times |
| `cancel_reminder` | Cancel a reminder by ID |
| `get_weather` | Current weather + clothing recommendations. Auto-detects location from IP. |
| `check_app_updates` | Homebrew, Mac App Store, and system software updates. macOS only. |
| `brew_list` | List all installed Homebrew formulae and casks. Requires `allow_brew`. |
| `brew_install` | Install a Homebrew formula or cask. Requires `allow_brew`. |
| `brew_upgrade` | Upgrade one or all Homebrew packages. Requires `allow_brew`. |
| `brew_uninstall` | Uninstall a Homebrew formula or cask. Requires `allow_brew`. |
| `get_docker_status` | Running containers with live CPU%, memory, image, status, and ports |
| `get_time_machine_status` | Last backup time, phase and progress if running, destination. macOS only. |
| `track_package` | Track UPS, USPS, FedEx, or DHL shipments by tracking number |

### Memory

| Tool | What it does |
|---|---|
| `read_memory` | Read the persistent memory file — facts and notes saved across sessions |
| `append_memory_note` | Append a concise note to the memory file for future recall |

### Research

| Tool | What it does |
|---|---|
| `deep_research` | Multi-step web research agent: plans subquestions, searches multiple sources, extracts and cross-verifies claims, returns a citation-backed answer. Takes 1-3 minutes. |

### Code Editing & Navigation

| Tool | What it does |
|---|---|
| `read_file_lines` | Read a file with line numbers, offset, and limit — large-file friendly. Requires `allow_file_read`. |
| `edit_file` | Targeted find-and-replace editing. Exact string match, fails if ambiguous. Requires `allow_file_write`. |
| `glob_files` | Find files by glob pattern (e.g. `**/*.py`). Skips .git, node_modules, .venv. |
| `grep_files` | Regex content search across files with optional context lines. Skips binary files. |
| `git_status` | Show branch, staged/unstaged/untracked files, and recent commits. |
| `git_diff` | Show git diff for unstaged or staged changes. |

### Sub-Agent Orchestration

| Tool | What it does |
|---|---|
| `list_agents` | List available sub-agents with names and descriptions |
| `run_agent` | Delegate a focused task to a named sub-agent (explorer, analyst, researcher, writer) running in an isolated subprocess with restricted tools. Requires `allow_agents`. |

### Self-Extension

| Tool | What it does |
|---|---|
| `create_tool` | Write, validate, and install a new MCP tool into `server.py`. Requires `allow_tool_creation`. |
| `list_user_tools` | List all tools installed via `create_tool` |

---

## Overclocking Support

Detected automatically from hardware and platform:

| Platform | CPU OC | GPU OC |
|---|---|---|
| Apple Silicon (M-series) | ✗ Not supported | ✗ Not supported |
| Intel Mac | ✗ Not supported (no BIOS) | ✗ Not supported (macOS) |
| Intel K/KF/KS — Windows/Linux | ✅ Intel XTU or BIOS | ✅ MSI Afterburner |
| AMD Ryzen — Windows/Linux | ✅ Ryzen Master / PBO | ✅ MSI Afterburner |

---

## Project Structure

```
SysControl/
├── agent.py                 # CLI entry-point shim
├── install-cli.sh           # One-line CLI installer (curl one-liner)
├── agent/
│   ├── cli.py               # Interactive terminal REPL
│   ├── core.py              # Shared agent logic: MCP client, streaming loop, helpers
│   ├── bridge.py            # JSON-over-stdio bridge for the Swift app
│   ├── agents.py            # Sub-agent specs: AgentSpec, AgentRegistry, built-in agents
│   ├── runner.py            # Sub-agent runner: isolated context, filtered tools
│   └── paths.py             # Path resolution (repo root, user data dir, memory file)
├── mcp/
│   ├── server.py            # MCP tool server (92 tools + self-extension)
│   └── prompt.json          # System prompt for the agent
├── deep_research/           # Deep research agent (iterative web research with citation verification)
├── swift/
│   ├── Package.swift         # SwiftPM package definition
│   ├── build.sh              # Builds the .app bundle and DMG
│   ├── install.sh            # One-line source installer
│   └── SysControl/           # SwiftUI source (App, Models, Views, Services, Storage)
├── scripts/
│   └── make_icon.py          # Generates the .icns app icon from source PNGs
├── pyproject.toml            # Python project config, dependencies, linting
├── VERSION                   # Current release version (single source of truth)
└── tests/                    # Pytest suite for agent core + MCP helpers
```

### Architecture

```
┌──────────────────────┐
│    SwiftUI App       │   Native macOS frontend
│  (swift/SysControl/) │   Onboarding, chat, settings, history
└────────┬─────────────┘
         │  JSON-over-stdio (bridge.py)
┌────────▼─────────────┐
│    Agent Core        │   Streaming agentic loop, LLM client
│  (agent/core.py)     │   Provider selection, tool dispatch
└────────┬─────────────┘
         │  JSON-RPC (stdio)
┌────────▼─────────────┐
│    MCP Server        │   92 tools, self-extension, permission checks
│  (mcp/server.py)     │   Concurrent tool execution via client pool
└──────────────────────┘
```

The Swift frontend communicates with the Python backend through `agent/bridge.py`, which speaks a simple JSON-over-stdio protocol. The bridge reuses the same `MCPClientPool` and streaming loop used by the CLI, so all tools and capabilities are shared across every interface.

---

## Entry Points

After installing via the [one-liner](#cli) (or `pip install -e .` from a clone):

| Script | Description |
|---|---|
| `syscontrol` | Interactive CLI agent |
| `syscontrol-server` | MCP server (stdio) |
| `syscontrol-cli-update` | Reinstall the CLI from the latest master |

From a clone without installing, use `uv run`:

| Command | Description |
|---|---|
| `uv run agent.py` | Interactive CLI agent |
| `uv run -m mcp.server` | MCP server (stdio) — for Claude Desktop integration |

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
