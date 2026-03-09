# SysControl

An AI agent for your Mac that answers questions about your system — and can extend itself with new tools on the fly.

SysControl gives a local or cloud LLM **57 real-time tools** covering every corner of your machine: CPU, RAM, GPU, disk, network, processes, iMessage, clipboard, browser control, weather, reminders, Docker, Time Machine, Wi-Fi, calendar, contacts, shell access, and more. The agent picks the right tools automatically, runs them in parallel, and synthesizes the results into plain-English answers.

**The standout feature — tool self-extension:** when you ask for something no tool covers, the agent offers to write and install a new one. It drafts the Python implementation, validates the syntax, runs a security scan, installs it permanently into the tool registry, and tells you to restart. No manual editing required.

Three ways to run it:

- **Terminal agent** (`agent.py`) — conversational REPL powered by Ollama (local) or Ollama Cloud
- **Remote bridge** (`remote.py`) — control your Mac from Telegram, WhatsApp, or Messenger
- **Claude Desktop** — connect `mcp/server.py` directly via MCP and use it with any Claude model

---

## Requirements

- Python **3.11** or later
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- [Ollama](https://ollama.com) (for local mode) **or** an Ollama Cloud API key (for cloud mode)

---

## Installation

```bash
# 1. Clone
git clone https://github.com/ks6573/SysControl.git
cd SysControl

# 2. Install uv (skip if already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Install dependencies
uv sync
```

---

## Agentic Terminal Agent

`agent.py` is a streaming, tool-calling REPL. The model autonomously selects, chains, and calls tools to answer your questions — you just talk to it.

### Quick Start

```bash
uv run agent.py
```

### Ending a Session

Say goodbye naturally — the agent recognises a wide range of exit phrases and closes gracefully:

```
bye  goodbye  farewell  see ya  cya  later  take care  peace
done  close  end  stop  adios  adieu  goodnight  ttyl  …
```

You can also press **Ctrl-C** at any time. Before the process exits, the agent will offer to save your session (see [Session Memory](#session-memory) below).

### Session Memory

SysControl can persist conversation context across sessions in `SysControl_Memory.md` (project root).

**How it works:**

- **On startup** — if `SysControl_Memory.md` exists the banner shows a notice and the file's contents are automatically injected into the system prompt, giving the agent awareness of past sessions.
- **On exit** — after any goodbye phrase or Ctrl-C, you are prompted:

  ```
  Save session? [yes/no/md/txt]:
  ```

  - `yes` / `md` — appends the conversation as a formatted Markdown section
  - `txt` — appends in plain text (no markdown syntax)
  - `no` — discards the session; nothing is written

- **Append-only** — new sessions are always appended beneath a timestamped `## Session — YYYY-MM-DD HH:MM` heading. Existing content is never overwritten.
- The file is plain text — you can freely edit or delete entries at any time.

> **Privacy notice:** SysControl stores only what you explicitly choose to save. No personal data is retained by the agent or the LLM. Ollama processes queries locally by default — see [ollama.com/tos](https://ollama.com/tos) for full details on cloud usage where applicable.

### CLI Flags

```
usage: agent.py [-h] [--provider {cloud,local}] [--model MODEL] [--api-key KEY]

Options:
  --provider {cloud,local}   Skip the interactive prompt
  --model MODEL              Override the default model
  --api-key KEY              Ollama API key for cloud (skips interactive prompt)
```

```bash
uv run agent.py                                            # interactive
uv run agent.py --provider local --model qwen2.5          # local, non-interactive
uv run agent.py --provider cloud --api-key sk-...         # cloud, non-interactive
```

### Local Mode (Ollama)

```bash
ollama pull qwen2.5   # recommended
ollama serve
uv run agent.py --provider local
```

**Tool-calling capable models:**

| Model | Pull command | Notes |
|---|---|---|
| `qwen2.5` | `ollama pull qwen2.5` | Default. Best tool use at 7B |
| `qwen3:8b` | `ollama pull qwen3:8b` | Newer, includes thinking mode |
| `llama3.1:8b` | `ollama pull llama3.1:8b` | Battle-tested alternative |
| `mistral` | `ollama pull mistral` | Lightweight and fast |

> Models without native tool-calling (e.g. `gemma3`) will error.

### Cloud Mode (Ollama Cloud)

```bash
uv run agent.py --provider cloud
# Enter your key when prompted — it is not echoed or stored in shell history
```

Get a key at [ollama.com/settings/keys](https://ollama.com/settings/keys). The default cloud model is `gpt-oss:120b`.

---

## What the Agent Can Do

### System monitoring & diagnostics

```
My Mac feels sluggish — what's going on?
Give me a full system snapshot
Which process is eating the most RAM right now?
What's filling up my disk?
Is my internet slow, and is it my router or my ISP?
What's connecting to the internet from my machine?
When did Time Machine last back up?
Show me system logs filtered for errors
What Docker containers are running and how much memory are they using?
```

### Hardware advice

```
I'm using Lightroom — what should I upgrade first?
Can I overclock my CPU? What tools would I use?
I'm running Docker and VS Code — how do I reduce RAM pressure?
```

### Actions & automation

```
Remind me in 2 hours to check my download
What should I wear today? (auto-detects your location)
Track my FedEx package 123456789012
Open Spotify
Set my volume to 40%
Copy this text to my clipboard: "Hello world"
Turn on Do Not Disturb
Send a message to +1 555 123 4567: "On my way"
What's in my clipboard?
Take a screenshot and describe it
Run: ls -la ~/Downloads
What are my calendar events this week?
```

### Web & browser

```
Search for the best Python library for PDF parsing
What does this page say? (reads your active browser tab)
Open github.com/anthropics in my browser
What's the latest version of Node.js?
```

### Self-extension — creating new tools

When you ask for something the agent can't do yet, it offers to build the tool:

```
You: What song is playing in Spotify right now?

Agent: I don't have a built-in tool for that. Want me to create one? (yes/no)

You: yes

Agent: I'll create a tool called `get_spotify_track` that uses osascript to
       query Spotify's current track name and artist. Shall I proceed?

You: yes

Agent: ✓ Tool `get_spotify_track` installed (no security warnings).
       Restart syscontrol and ask me again — it'll be available immediately.
```

The agent writes a Python function, validates the syntax, scans for dangerous patterns (`eval`, `exec`, etc.), and appends the tool to `mcp/server.py` permanently. It won't write to disk if the code fails the compile check.

To enable tool creation, add to `~/.syscontrol/config.json`:

```json
{ "allow_tool_creation": true }
```

---

## Permissions & Security

Sensitive tools are **disabled by default**. Enable them individually in `~/.syscontrol/config.json`:

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
  "allow_tool_creation":   true
}
```

Enable only the permissions you need. Each disabled tool returns an error with the exact config flag required to enable it.

---

## Remote Messaging Bridge

`remote.py` lets you control your Mac from **Telegram**, **WhatsApp**, or **Facebook Messenger** via a Cloudflare-tunnelled webhook — no port-forwarding required.

Full setup instructions, config reference, and security notes are in [agent/REMOTE_SETUP.md](agent/REMOTE_SETUP.md).

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
      "args": ["run", "/absolute/path/to/SyscontrolMCP/mcp/server.py"],
      "env": {}
    }
  }
}
```

Use `which uv` to get the uv binary path.

**2. Set the system prompt**

Create a Claude Desktop Project and paste the contents of `system_prompt.prompt` from `mcp/prompt.json` into the Project Instructions field.

**3. Restart Claude Desktop** — `system-monitor` will appear in the MCP servers list.

---

## Tools (57 total)

### Monitoring

| Tool | What it does |
|---|---|
| `get_cpu_usage` | CPU load (total + per-core), clock frequency, inline bar chart |
| `get_ram_usage` | RAM and swap — used, available, percent, inline stacked chart |
| `get_gpu_usage` | GPU load, VRAM, temperature per device (NVIDIA / pynvml), inline grouped chart |
| `get_disk_usage` | Per-partition space and cumulative I/O counters |
| `get_network_usage` | Cumulative bytes sent/received and per-interface status |
| `get_realtime_io` | **Live** disk read/write and network download/upload speed (MB/s) |
| `get_top_processes` | Top N processes by CPU or memory |
| `get_full_snapshot` | Single call: CPU + RAM + GPU + disk + network + top processes |
| `get_system_alerts` | Triage scan returning prioritized critical/warning alerts |

### System & Hardware

| Tool | What it does |
|---|---|
| `get_device_specs` | Static profile: CPU model, core count, RAM, GPU VRAM, disks, OS |
| `get_battery_status` | Percent, charging state, time remaining |
| `get_temperature_sensors` | CPU/motherboard sensors (Linux/Windows). On macOS explains the limitation. |
| `get_system_uptime` | Boot time, uptime, 1/5/15-min load averages |
| `get_hardware_profile` | Live pressure + specs + OC capability + per-component upgrade feasibility + workload bottleneck |

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
| `network_latency_check` | Pings gateway, Cloudflare, Google DNS **in parallel** and diagnoses where slowness begins |
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
| `take_screenshot` | Full-screen PNG, returned inline. Optionally save to file. Silent. macOS only. |

### App Control & System

| Tool | What it does |
|---|---|
| `open_app` | Open an app by name (`open -a`). macOS only. |
| `quit_app` | Gracefully quit (AppleScript) or force-kill an app. macOS only. |
| `get_volume` | Output volume, input volume, alert volume, mute state |
| `set_volume` | Set system output volume (0–100) |
| `get_frontmost_app` | Return the name of the focused application |
| `toggle_do_not_disturb` | Enable/disable Focus / DnD |
| `run_shortcut` | Run a named Shortcut via `shortcuts run`. macOS 12+. |

### File I/O & Shell

| Tool | What it does |
|---|---|
| `read_file` | Read a text file (up to 32,000 chars) |
| `write_file` | Write text to any path, creating directories as needed |
| `run_shell_command` | Execute a bash command and return stdout/stderr. **Disabled by default.** |

### Calendar, Contacts & Logs

| Tool | What it does |
|---|---|
| `get_calendar_events` | Upcoming events from Calendar.app for the next N days. macOS only. |
| `get_contact` | Search Contacts.app by name — phone and email. macOS only. |
| `get_startup_items` | Auto-start items (macOS LaunchAgents, Windows Registry, Linux `.desktop`) |
| `tail_system_logs` | Last N lines of the system log with optional keyword filter |

### Utilities

| Tool | What it does |
|---|---|
| `set_reminder` | Schedule a macOS notification. Accepts `"in 2 hours"`, `"tomorrow at 9am"`, etc. |
| `list_reminders` | All pending reminders with IDs and fire times |
| `cancel_reminder` | Cancel a reminder by ID |
| `get_weather` | Current weather + clothing recommendations. Auto-detects location from IP. |
| `check_app_updates` | Homebrew (formulae + casks), Mac App Store, and system software updates. macOS only. |
| `get_docker_status` | Running containers with live CPU%, memory, image, status, and ports |
| `get_time_machine_status` | Last backup time, phase and progress if running, destination. macOS only. |
| `track_package` | Track UPS, USPS, FedEx, or DHL shipments by tracking number |

### Self-Extension

| Tool | What it does |
|---|---|
| `create_tool` | Write, validate, and install a new MCP tool into `server.py`. Requires `allow_tool_creation`. |
| `list_user_tools` | List all tools installed via `create_tool` |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  agent.py (shim)         remote.py (shim)                   │
│       │                        │                            │
│       ▼                        ▼                            │
│  agent/cli.py            agent/remote.py                    │
│  Streaming REPL          FastAPI webhook server             │
│  (local / cloud LLM)     Telegram · WhatsApp · Messenger    │
│       │                        │                            │
│       └──────────┬─────────────┘                            │
│                  │  agent/core.py                           │
│                  │  MCPClientPool (up to 4 workers)         │
│                  │  ThreadPoolExecutor: parallel tool calls  │
└──────────────────┼──────────────────────────────────────────┘
                   │ JSON-RPC 2.0 over stdio
                   ▼
┌─────────────────────────────────────────────────────────────┐
│                      mcp/server.py                          │
│                                                             │
│  57 tools  ─  psutil, pynvml, matplotlib, subprocess       │
│  ReminderChecker background thread (15s polling)           │
│  Self-extension: create_tool writes new tools at runtime   │
└─────────────────────────────────────────────────────────────┘
```

**Key design decisions:**

| Feature | Detail |
|---|---|
| **Parallel tool execution** | `MCPClientPool` spawns up to 4 `mcp/server.py` subprocesses. When the LLM calls multiple tools in one turn, they run concurrently via `ThreadPoolExecutor`. |
| **Parallel startup** | MCP init and system prompt loading happen in parallel threads — shaves ~200ms off cold start. |
| **Internally parallel tools** | `network_latency_check` pings 4 targets simultaneously. `get_time_machine_status` runs 3 `tmutil` calls simultaneously. |
| **Self-extending registry** | `create_tool` validates, syntax-checks, and appends a new tool to `server.py` without interrupting the running session. |
| **Permission gating** | Sensitive tools are off by default. Each gate is a single flag in `~/.syscontrol/config.json`. |
| **Buffered streaming** | Token fragments are collected in a list and joined once, avoiding O(n²) string copies during long responses. |
| **Graceful shutdown** | `MCPClient.close()` sends SIGTERM → waits 2s → SIGKILL, preventing zombie server processes. |
| **Graceful exit phrases** | 25+ natural goodbye expressions (`bye`, `farewell`, `cya`, `goodnight`, …) all trigger a clean shutdown with an optional memory-save prompt. |
| **Append-only session memory** | `SysControl_Memory.md` is never overwritten — each saved session is timestamped and appended. On startup the file is injected into the system prompt so the agent has full prior context. |
| **Secure API key input** | `getpass.getpass()` — key never echoed or stored in shell history. |
| **Remote session isolation** | Each `(platform, chat_id)` pair has its own thread-safe message history. |

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
SyscontrolMCP/
├── agent.py                   # Entry-point shim → agent/cli.py
├── remote.py                  # Entry-point shim → agent/remote.py
│
├── agent/
│   ├── core.py                # MCPClient, MCPClientPool, shared helpers
│   ├── cli.py                 # Streaming agentic REPL (local or cloud LLM)
│   ├── remote.py              # Telegram / WhatsApp / Messenger bridge
│   └── REMOTE_SETUP.md        # Full remote bridge setup guide
│
├── mcp/
│   ├── server.py              # MCP server — 57 tools, JSON-RPC dispatcher
│   └── prompt.json            # System prompt (paste into Claude Desktop Projects)
│
├── SysControl_Memory.md       # Auto-created on first save; append-only session log
├── claude_desktop_config.json # Ready-to-use Claude Desktop config (update paths)
├── pyproject.toml             # Project metadata and dependencies (uv)
└── uv.lock                    # Pinned dependency versions
```

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| `psutil` | ≥ 5.9.0 | System metrics (CPU, RAM, disk, network, processes) |
| `nvidia-ml-py` | ≥ 12.0.0 | GPU metrics via NVML (gracefully disabled on non-NVIDIA hardware) |
| `matplotlib` | ≥ 3.7.0 | Inline chart generation for CPU, RAM, and GPU tools |
| `openai` | ≥ 2.26.0 | OpenAI-compatible client for Ollama (local and cloud) |
| `fastapi` | ≥ 0.111.0 | Webhook server for the remote messaging bridge |
| `uvicorn` | ≥ 0.29.0 | ASGI server for FastAPI |
| `httpx` | ≥ 0.27.0 | HTTP client for outbound messaging API calls |

```bash
# Install with dev tools (ruff, mypy, pytest)
uv sync --extra dev
```
