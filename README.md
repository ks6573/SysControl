# SysControl

An AI agent for your Mac that answers questions about your system — and can extend itself with new tools on the fly.

83 real-time tools covering CPU, RAM, GPU, disk, network, processes, iMessage, email, clipboard, browser, weather, reminders, Docker, Time Machine, Wi-Fi, calendar, contacts, Notes, Homebrew, media control, file management, Spotlight search, spreadsheets, Word documents, PDFs, deep web research, and more. The agent picks the right tools automatically, runs them in parallel, and answers in plain English.

Three ways to run it — pick whichever fits your workflow:

| | How | Best for |
|---|---|---|
| **App** | [Download the `.app`](#app-recommended) | One-click native macOS experience — no setup required |
| **CLI** | `uv run agent.py` | Terminal-first workflow, scripting, SSH sessions |
| **Claude Desktop** | MCP server | Using SysControl tools inside Claude Desktop |

All interfaces share the same agent, tools, and providers — they're interchangeable.

---

## App (Recommended)

A native SwiftUI app with streaming chat, Markdown rendering, chat history sidebar, and auto-save — no Python, no terminal, no dependencies to install. Just download, open, and configure your provider in Settings.

### Download

**Option A — Pre-built DMG** (no Xcode required):

Download the latest `SysControl.dmg` from [GitHub Releases](https://github.com/ks6573/Syscontrol/releases), drag to Applications, then bypass Gatekeeper on first launch (the app is ad-hoc signed, not notarized):

```bash
xattr -r -d com.apple.quarantine /Applications/SysControl.app
```

Or right-click the app → **Open** → **Open** the first time.

**Option B — Install from source** (compiles locally, bypasses Gatekeeper automatically):

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/ks6573/Syscontrol/master/swift/install.sh)"
```

To update later: use **Check for Updates** in the app (⇧⌘U), or run `syscontrol-update` from Terminal.

To uninstall: re-run with `--uninstall`.

**Option C — Build manually:**

```bash
git clone https://github.com/ks6573/Syscontrol.git
cd Syscontrol/swift
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

## Requirements (CLI only)

- Python **3.11** or later
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- [Ollama](https://ollama.com) (local mode) **or** an Ollama Cloud API key (cloud mode)

---

## Installation (CLI only)

```bash
git clone https://github.com/ks6573/Syscontrol.git
cd Syscontrol

# Install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

uv sync
```

---

## Terminal Agent

```bash
uv run agent.py
```

### CLI Flags

```bash
uv run agent.py                                          # interactive
uv run agent.py --provider local --model qwen3:30b      # local, skip prompt
uv run agent.py --provider cloud --api-key sk-...       # cloud, skip prompt
```

### Local Mode (Ollama)

```bash
ollama pull qwen3:30b   # recommended
ollama serve
uv run agent.py --provider local
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
uv run agent.py --provider cloud
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
  "allow_brew":            true
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
      "args": ["run", "/absolute/path/to/Syscontrol/mcp/server.py"],
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

## Tools (64 total)

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
├── gui.py                   # PySide6 GUI entry-point shim
├── remote.py                # Remote bridge entry-point shim
├── agent/
│   ├── cli.py               # Interactive terminal REPL
│   ├── core.py              # Shared agent logic: MCP client, streaming loop, helpers
│   ├── bridge.py            # JSON-over-stdio bridge for the Swift app
│   ├── paths.py             # Frozen-app-aware path resolution
│   └── remote.py            # Telegram / WhatsApp / Messenger webhook bridge
├── mcp/
│   ├── server.py            # MCP tool server (83 tools + self-extension)
│   └── prompt.json          # System prompt for the agent
├── deep_research/           # Deep research agent (iterative web research with citation verification)
├── swift/
│   ├── Package.swift         # SwiftPM package definition
│   ├── build.sh              # Build + bundle script
│   ├── install.sh            # One-line installer
│   └── SysControl/           # SwiftUI source (App, Models, Views, Services, Storage)
├── scripts/
│   ├── build_macos.sh        # PyInstaller macOS build
│   └── build_dmg.sh          # DMG creation script
├── pyproject.toml            # Python project config, dependencies, linting
├── VERSION                   # Current release version
└── SysControl.command        # Double-click launcher for the GUI
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
│    MCP Server        │   83 tools, self-extension, permission checks
│  (mcp/server.py)     │   Concurrent tool execution via client pool
└──────────────────────┘
```

The Swift frontend communicates with the Python backend through `agent/bridge.py`, which speaks a simple JSON-over-stdio protocol. The bridge reuses the same `MCPClientPool` and streaming loop used by the CLI, so all tools and capabilities are shared across every interface.

---

## Entry Points

| Command | Description |
|---|---|
| `uv run agent.py` | Interactive CLI agent |
| `uv run remote.py` | Remote bridge (Telegram, WhatsApp, Messenger) |
| `uv run gui.py` | PySide6 desktop GUI (requires `uv pip install -e '.[gui]'`) |

After `pip install -e .`, these registered scripts also work:

| Script | Description |
|---|---|
| `syscontrol` | CLI agent |
| `syscontrol-server` | MCP server (stdio) |
| `syscontrol-gui` | PySide6 GUI |

