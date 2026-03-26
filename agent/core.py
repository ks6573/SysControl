#!/usr/bin/env python3
"""
SysControl Agent — Core utilities.

Provides the MCP client, client pool, and shared helpers used by both the
CLI (agent/cli.py) and the remote bridge (agent/remote.py).
"""

import base64
import binascii
import contextlib
import hashlib
import json
import os
import re
import select
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from functools import lru_cache
from typing import IO

try:
    import fcntl as fcntl_mod  # noqa: F401 — re-exported for cli.py / server.py
    HAS_FCNTL = True
except ImportError:
    fcntl_mod = None  # type: ignore[assignment]  # noqa: F401
    HAS_FCNTL = False

import openai
from openai import OpenAI  # noqa: F401 — re-exported for downstream imports

from agent.paths import MEMORY_FILE, PROMPT_PATH, SERVER_PATH  # frozen-app-aware paths

# ── Shared constants ─────────────────────────────────────────────────────────

EXIT_PHRASES: frozenset[str] = frozenset({
    "exit", "quit", "bye", "goodbye", "good bye", "farewell",
    "see ya", "see you", "cya", "later", "take care", "peace",
    "done", "close", "end", "stop", ":q", "q", "adios", "adieu",
    "ttyl", "ttfn", "night", "goodnight", "good night",
})

MAX_HISTORY_MESSAGES = 40  # ~20 user turns; keeps context within model limits

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_TOKENS         = 16384
POOL_SIZE          = 4          # max parallel MCP worker processes
MAX_PARALLEL_TOOLS = POOL_SIZE  # batch size capped to pool capacity
MAX_TOOL_ROUNDS    = 15         # circuit-breaker for runaway tool-call loops
_MAX_CHART_BYTES   = 10 * 1024 * 1024  # 10 MB cap on decoded chart images
_CHART_FILE_PREFIX = "syscontrol_chart_"

RESPONSE_STYLE_GUIDANCE: str = (
    "\n\n---\n\n# Response Style\n\n"
    "When replying to the user:\n"
    "- Avoid a single dense paragraph for non-trivial answers.\n"
    "- Prefer a short direct lead, then concise bullets or numbered steps when helpful.\n"
    "- Prefer headings + bullet lists over markdown tables unless the user explicitly asks for a table.\n"
    "- Insert blank lines between sections so responses are easy to scan.\n"
    "- Use markdown structure naturally (headings, bullets, code blocks) when it improves clarity.\n"
    "- Keep simple requests short (1-2 sentences).\n"
    "- For actionable instructions, provide concrete commands/examples.\n"
)

# ── Provider config ───────────────────────────────────────────────────────────

CLOUD_MODEL    = "gpt-oss:120b"
CLOUD_BASE_URL = "https://ollama.com/v1"

LOCAL_MODEL    = "qwen3:30b"  # any model pulled via: ollama pull <model>
LOCAL_BASE_URL = "http://localhost:11434/v1"
LOCAL_API_KEY  = "ollama"   # Ollama doesn't require a real key

# ANSI colours — only emitted when stdout is a real terminal.
_USE_COLOR = sys.stdout.isatty()
RESET   = "\033[0m"  if _USE_COLOR else ""
BOLD    = "\033[1m"  if _USE_COLOR else ""
DIM     = "\033[2m"  if _USE_COLOR else ""
CYAN    = "\033[36m" if _USE_COLOR else ""
GREEN   = "\033[32m" if _USE_COLOR else ""
YELLOW  = "\033[33m" if _USE_COLOR else ""
BLUE    = "\033[34m" if _USE_COLOR else ""
WHITE   = "\033[97m" if _USE_COLOR else ""   # bright white — used for bold text
MAGENTA = "\033[35m" if _USE_COLOR else ""   # used for inline code

# ── MCP Client ────────────────────────────────────────────────────────────────

_STDERR_READ_TIMEOUT = 2.0   # seconds to wait for stderr output on crash
_STDERR_MAX_BYTES    = 4096  # cap stderr reads to avoid memory bloat


def _read_stderr_safe(
    pipe: IO[str] | IO[bytes] | None,
    timeout: float = _STDERR_READ_TIMEOUT,
) -> str:
    """Read available stderr output without blocking indefinitely.

    Uses ``select()`` on Unix to check readability before reading.
    Falls back to an empty string if nothing is available within *timeout*.

    Args:
        pipe: Stderr pipe from a subprocess (text or binary mode), or ``None``.
        timeout: Maximum seconds to wait for data.  Defaults to 2.0.

    Returns:
        Stripped stderr text, or empty string if unavailable or on error.
    """
    if pipe is None:
        return ""
    try:
        fd = pipe.fileno()
    except (ValueError, OSError):
        return ""
    try:
        ready, _, _ = select.select([fd], [], [], timeout)
    except (ValueError, OSError):
        return ""
    if not ready:
        return ""
    try:
        # Read at the fd level (raw bytes) rather than through the TextIOWrapper.
        # This is intentional: on crash paths the wrapper's internal buffer may
        # be in an inconsistent state, and the process is torn down immediately
        # after this read — so wrapper coherence does not matter.
        data = os.read(fd, _STDERR_MAX_BYTES)
        return data.decode("utf-8", errors="replace").strip()
    except (OSError, ValueError):
        return ""


class MCPClient:
    """Minimal JSON-RPC client that talks to mcp/server.py over stdio."""

    def __init__(self) -> None:
        """Spawn the MCP server subprocess and perform the JSON-RPC handshake.

        In a frozen PyInstaller bundle the executable re-invokes itself with
        ``--mcp-server`` so the entry-point can dispatch to mcp/server.py.
        Otherwise the server is launched directly via ``sys.executable``.

        Raises:
            RuntimeError: If the subprocess fails to start or the handshake
                times out / returns an unexpected response.
        """
        # In a frozen PyInstaller bundle sys.executable is the app binary,
        # not a Python interpreter.  Re-invoke ourselves with a flag so the
        # main entry-point can dispatch to the MCP server.
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--mcp-server"]
        else:
            cmd = [sys.executable, str(SERVER_PATH)]

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self.proc.stdin is not None, "Popen stdin must be a pipe"
        assert self.proc.stdout is not None, "Popen stdout must be a pipe"
        self._id   = 0
        self._lock = threading.Lock()   # serialise writes/reads on this pipe
        self._chart_files: list[str] = []
        self._initialize()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _send(
        self,
        method: str,
        params: dict | None = None,
        _read_timeout: float | None = None,
    ) -> dict:
        """Send a JSON-RPC request and return the parsed response.

        Args:
            method: JSON-RPC method name.
            params: Optional parameters dict.
            _read_timeout: If set, wait at most this many seconds for the
                server to produce a response line.  ``None`` (default) blocks
                indefinitely — suitable for normal tool calls where the server
                is known-healthy.  Used by ``_initialize`` to enforce a
                startup deadline.

        Raises:
            RuntimeError: If the server crashes or closes its pipe.
            TimeoutError: If *_read_timeout* is set and the server does not
                respond in time.
        """
        with self._lock:
            msg: dict = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
            if params:
                msg["params"] = params
            try:
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                err = _read_stderr_safe(self.proc.stderr)
                raise RuntimeError(
                    f"MCP server crashed."
                    f"{(' Server error: ' + err) if err else ''}"
                ) from exc

            # Gate the blocking readline() behind select() when a timeout is
            # requested, so callers (e.g. _initialize) cannot hang forever.
            if _read_timeout is not None:
                try:
                    ready, _, _ = select.select(
                        [self.proc.stdout], [], [], _read_timeout,
                    )
                except (ValueError, OSError):
                    ready = []
                if not ready:
                    raise TimeoutError(
                        f"MCP server did not respond to '{method}' within "
                        f"{_read_timeout:.1f}s — is mcp/server.py healthy?"
                    )

            raw = self.proc.stdout.readline()
            if not raw:
                err = _read_stderr_safe(self.proc.stderr)
                raise RuntimeError(
                    f"MCP server closed unexpectedly."
                    f"{(' Server error: ' + err) if err else ''}"
                )
            return json.loads(raw)

    def _notify(self, method: str) -> None:
        with self._lock:
            msg = {"jsonrpc": "2.0", "method": method}
            try:
                self.proc.stdin.write(json.dumps(msg) + "\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                err = _read_stderr_safe(self.proc.stderr)
                raise RuntimeError(
                    f"MCP server crashed during notification '{method}'."
                    f"{(' Server error: ' + err) if err else ''}"
                ) from exc

    def _initialize(self, timeout: float = 10.0) -> None:
        """Perform the JSON-RPC handshake with a deadline.

        Args:
            timeout: Maximum seconds to wait for the server to respond.

        Raises:
            RuntimeError: If the server process exits before responding.
            TimeoutError: If the server does not respond within *timeout* seconds.
        """
        # Detect early exit before attempting the handshake — gives a clearer
        # error than a BrokenPipeError from _send.
        if self.proc.poll() is not None:
            err = _read_stderr_safe(self.proc.stderr)
            raise RuntimeError(
                f"MCP server exited before handshake (code {self.proc.returncode})."
                f"{(' Server error: ' + err) if err else ''}"
            )

        # _read_timeout gates the blocking readline() inside _send with
        # select(), so this call cannot hang beyond the deadline.
        self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities":    {},
            "clientInfo":      {"name": "syscontrol-agent", "version": "1.0"},
        }, _read_timeout=timeout)

        self._notify("initialized")

    def list_tools(self) -> list[dict]:
        resp = self._send("tools/list")
        return resp.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict | None = None) -> str:
        """Execute a tool by name and return the text result.

        When the tool produces an image (e.g. chart), the image is saved to
        a temp file and a ``[chart_image:/path]`` marker is appended.  Temp
        files are tracked in ``_chart_files`` and cleaned up by ``close()``.

        Args:
            name: MCP tool name to invoke.
            arguments: Tool arguments dict, or ``None`` for no arguments.

        Returns:
            Combined text content from the tool, with ``[chart_image:...]``
            markers appended for any image content items.
        """
        resp = self._send("tools/call", {"name": name, "arguments": arguments or {}})
        content = resp.get("result", {}).get("content", [])
        if not content:
            return "[no content returned]"

        text_parts: list[str] = []
        for item in content:
            if item.get("type") == "text":
                text_parts.append(item.get("text", ""))
            elif item.get("type") == "image":
                img_data = item.get("data", "")
                if not img_data:
                    continue
                try:
                    decoded = base64.b64decode(img_data, validate=True)
                except (binascii.Error, ValueError):
                    text_parts.append("[chart image: decode error]")
                    continue
                if len(decoded) > _MAX_CHART_BYTES:
                    text_parts.append("[chart image: exceeds size limit]")
                    continue
                digest = hashlib.md5(img_data[:64].encode()).hexdigest()[:10]  # noqa: S324
                path = os.path.join(
                    tempfile.gettempdir(),
                    f"{_CHART_FILE_PREFIX}{digest}.png",
                )
                with open(path, "wb") as f:
                    f.write(decoded)
                self._chart_files.append(path)
                text_parts.append(f"\n[chart_image:{path}]")

        return "\n".join(text_parts) if text_parts else "[no content returned]"

    def close(self) -> None:
        """Gracefully shut down the subprocess: close stdin → terminate → kill.

        Each step is guarded so a failure at any stage does not prevent the
        next attempt.  A final ``wait()`` confirms the process is reaped.
        Chart temp files created by ``call_tool()`` are cleaned up here.
        """
        # Clean up chart temp files
        for path in self._chart_files:
            with contextlib.suppress(OSError):
                os.remove(path)
        self._chart_files.clear()

        pid = self.proc.pid
        try:
            self.proc.stdin.close()
        except Exception as exc:
            sys.stderr.write(f"[syscontrol] MCPClient.close stdin (pid={pid}): {exc}\n")
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
            return  # clean exit — no need to escalate
        except Exception as exc:
            sys.stderr.write(f"[syscontrol] MCPClient.close terminate (pid={pid}): {exc}\n")
        try:
            self.proc.kill()
            self.proc.wait(timeout=2)  # reap to avoid zombie
        except Exception:
            pass  # best-effort — process may already be gone


# ── MCP Client Pool ───────────────────────────────────────────────────────────


def _parse_tool_call_args(tc: dict) -> tuple[str, dict]:
    """Extract tool name and parsed arguments from a tool-call dict.

    Args:
        tc: An OpenAI-format tool-call dict with ``function.name`` and
            ``function.arguments`` keys.

    Returns:
        A ``(name, args)`` tuple.  *args* defaults to ``{}`` on parse failure.
    """
    name = tc["function"]["name"]
    assert name, "Tool call has empty name — malformed LLM response"
    try:
        args = json.loads(tc["function"]["arguments"])
    except json.JSONDecodeError:
        args = {}
    return name, args


class MCPClientPool:
    """
    Manages a pool of MCPClient instances so independent tool calls can be
    executed concurrently — each call gets its own subprocess/pipe.

    Workers are lazily initialised: the primary client is created eagerly and
    extras are spawned only when a parallel batch actually needs them.
    """

    def __init__(self, primary: MCPClient, pool_size: int = POOL_SIZE) -> None:
        """Initialise the pool with a pre-created primary client.

        Args:
            primary: The eagerly-created MCP client placed at index 0.
                The pool takes ownership and will close it on ``close_all()``.
            pool_size: Maximum number of concurrent MCP clients.  Extra clients
                are spawned lazily when a parallel batch actually needs them.
        """
        self._clients: dict[int, MCPClient] = {0: primary}
        self._pool_size = pool_size
        self._pool_lock = threading.Lock()
        self._parallel_safe: set[str] | None = None  # lazily populated

    def _get_or_create(self, index: int) -> MCPClient:
        assert 0 <= index < self._pool_size, (
            f"Pool index {index} out of range [0, {self._pool_size})"
        )

        # Fast path — already created.
        with self._pool_lock:
            if index in self._clients:
                return self._clients[index]

        # Construct the new client OUTSIDE the lock — MCPClient.__init__ spawns
        # a subprocess and runs the MCP handshake, which can take 100–200 ms.
        # Holding the lock for that entire time would block every other thread.
        new_client = MCPClient()

        with self._pool_lock:
            # Re-check under lock: another thread may have beaten us.
            # If so, discard our new_client to avoid a leaked subprocess.
            if index in self._clients:
                new_client.close()
                return self._clients[index]
            self._clients[index] = new_client
            return new_client

    # Sentinel: distinguishes "server unreachable, allow everything" from a
    # legitimately loaded (but possibly empty) set of safe tool names.
    _FALLBACK: frozenset[str] = frozenset()

    def _get_parallel_safe(self) -> frozenset[str] | set[str]:
        """Return the set of tool names that are safe to run concurrently.

        Lazily fetches the tool list from the primary MCP client on first call
        and caches it for the lifetime of the pool.
        """
        if self._parallel_safe is None:
            try:
                tools = self._clients[0].list_tools()  # primary always at index 0
                self._parallel_safe = {
                    t["name"] for t in tools if t.get("parallel", True)
                }
            except Exception:
                # Server unreachable — use sentinel so _is_parallel_safe
                # falls back to allowing everything (original behaviour).
                self._parallel_safe = self._FALLBACK
        return self._parallel_safe

    def _is_parallel_safe(self, name: str) -> bool:
        safe = self._get_parallel_safe()
        if safe is self._FALLBACK:
            return True   # error fallback: allow everything
        return name in safe

    def call_tools_parallel(
        self, tool_calls: list[dict]
    ) -> list[tuple[str, str, str]]:
        """
        Execute tool calls with parallel-safety enforcement.

        Batch-safe tools (read-only, fast, no side effects) run concurrently,
        capped at MAX_PARALLEL_TOOLS per batch.  Unsafe tools (blocking,
        state-mutating, or large-output) always run sequentially on the primary
        client.  Results are returned in the original request order.
        """
        if len(tool_calls) == 1:
            # Fast path: no thread overhead for a single call.
            tc = tool_calls[0]
            name, args = _parse_tool_call_args(tc)
            result = self._clients[0].call_tool(name, args)  # primary client
            return [(tc["id"], name, result)]

        # Partition by parallel safety in a single pass, preserving original indices.
        safe_indexed: list[tuple[int, dict]]   = []
        serial_indexed: list[tuple[int, dict]] = []
        for i, tc in enumerate(tool_calls):
            (safe_indexed if self._is_parallel_safe(tc["function"]["name"])
             else serial_indexed).append((i, tc))

        results: list[tuple[int, str, str, str]] = []  # (orig_idx, tc_id, name, result)

        def _run_one(
            order: int, tc: dict, client: MCPClient
        ) -> tuple[int, str, str, str]:
            name, args = _parse_tool_call_args(tc)
            return (order, tc["id"], name, client.call_tool(name, args))

        # Run parallel-safe calls in batches of at most MAX_PARALLEL_TOOLS.
        for batch_start in range(0, len(safe_indexed), MAX_PARALLEL_TOOLS):
            batch = safe_indexed[batch_start:batch_start + MAX_PARALLEL_TOOLS]
            n_workers = min(len(batch), self._pool_size)
            with ThreadPoolExecutor(max_workers=n_workers) as ex:
                futures = [
                    ex.submit(_run_one, order, tc, self._get_or_create(slot % n_workers))
                    for slot, (order, tc) in enumerate(batch)
                ]
                for fut in as_completed(futures):
                    results.append(fut.result())

        # Run serial calls one at a time on the primary client.
        for order, tc in serial_indexed:
            results.append(_run_one(order, tc, self._clients[0]))  # primary client

        results.sort(key=lambda x: x[0])
        return [(tc_id, name, result) for _, tc_id, name, result in results]

    def close_all(self) -> None:
        for client in self._clients.values():
            client.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    """Load and cache the system prompt — file is read once per process."""
    data = json.loads(PROMPT_PATH.read_text(encoding="utf-8"))
    return data["system_prompt"]["prompt"]


def mcp_to_openai_tools(mcp_tools: list[dict]) -> list[dict]:
    """Convert MCP tool definitions to the OpenAI/Ollama tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name":        t["name"],
                "description": t.get("description", ""),
                "parameters":  t.get("inputSchema", {
                    "type":       "object",
                    "properties": {},
                    "required":   [],
                }),
            },
        }
        for t in mcp_tools
    ]


# ── Shared helpers (used by CLI, GUI worker, and settings dialog) ────────────


def load_memory() -> str | None:
    """Return the contents of SysControl_Memory.md if it exists, else None."""
    if MEMORY_FILE.exists():
        text = MEMORY_FILE.read_text(encoding="utf-8").strip()
        return text if text else None
    return None


def prune_history(messages: list[dict], max_messages: int = MAX_HISTORY_MESSAGES) -> list[dict]:
    """Trim history while preserving tool-call coherence.

    Groups the history into user-anchored turn chunks, then drops the oldest
    chunks until the total fits within the budget.
    """
    if len(messages) <= max_messages:
        return messages

    groups: list[list[dict]] = []
    current: list[dict] = []
    for msg in messages:
        if msg["role"] == "user" and current:
            groups.append(current)
            current = []
        current.append(msg)
    if current:
        groups.append(current)

    # Find first group index where cumulative tail count <= max_messages.
    total = sum(len(g) for g in groups)
    cutoff = 0
    while cutoff < len(groups) and total > max_messages:
        total -= len(groups[cutoff])
        cutoff += 1

    return [msg for group in groups[cutoff:] for msg in group]


def fetch_ollama_models(base_url: str = "http://localhost:11434") -> list[str]:
    """Return sorted list of locally installed Ollama model names.

    Returns an empty list if Ollama is not running or unreachable (3 s timeout).
    """
    try:
        req = urllib.request.Request(
            f"{base_url}/api/tags",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            data = json.loads(r.read().decode())
        return sorted(m["name"] for m in data.get("models", []))
    except Exception as exc:
        sys.stderr.write(f"[syscontrol] fetch_ollama_models: {exc}\n")
        return []


# ── Markdown → ANSI colorizer ─────────────────────────────────────────────────

# Pre-compiled patterns for speed (called on every streamed line).
_MD_HEADER   = re.compile(r"^(#{1,3})\s+(.+)$")
_MD_BOLD     = re.compile(r"\*\*(.+?)\*\*")
_MD_ITALIC   = re.compile(r"\*([^*\n]+?)\*")
_MD_CODE     = re.compile(r"`([^`\n]+)`")
_MD_BULLET   = re.compile(r"^(\s*)[-•*]\s+")
_MD_NUMBERED = re.compile(r"^(\s*)(\d+)\.\s+")
_MD_HR       = re.compile(r"^[-=_]{3,}\s*$")


def colorize(line: str) -> str:
    """
    Convert one line of markdown to ANSI-coloured plain text.
    Markers are consumed; only the coloured content is printed.
    """
    # Horizontal rule  ---  ===  ___
    if _MD_HR.match(line):
        return f"{DIM}{'─' * 56}{RESET}"

    # # / ## / ### heading
    m = _MD_HEADER.match(line)
    if m:
        level = len(m.group(1))
        prefix = "  " * (level - 1)          # indent sub-headings slightly
        return f"{prefix}{BOLD}{CYAN}{m.group(2)}{RESET}"

    # Bullet list  - item  or  • item
    m = _MD_BULLET.match(line)
    if m:
        indent = m.group(1)
        rest   = line[m.end():]  # everything after the marker
        rest   = _apply_inline(rest)
        return f"{indent}{CYAN}•{RESET} {rest}"

    # Numbered list  1. item
    m = _MD_NUMBERED.match(line)
    if m:
        indent = m.group(1)
        num    = m.group(2)
        rest   = line[m.end():]
        rest   = _apply_inline(rest)
        return f"{indent}{CYAN}{num}.{RESET} {rest}"

    # Regular line — apply inline markers only
    return _apply_inline(line)


# Pre-built replacement strings with backreferences — faster than lambdas
# because no per-call closure allocation is needed.
_BOLD_REPL   = f"{BOLD}{WHITE}\\1{RESET}"
_ITALIC_REPL = f"{YELLOW}\\1{RESET}"
_CODE_REPL   = f"{MAGENTA}\\1{RESET}"


def _apply_inline(text: str) -> str:
    """Apply bold / italic / code colour to inline spans, consuming the markers."""
    # **bold** → bright white bold (process before *italic* to avoid collision)
    text = _MD_BOLD.sub(_BOLD_REPL, text)
    # *italic* → yellow
    text = _MD_ITALIC.sub(_ITALIC_REPL, text)
    # `code` → magenta
    text = _MD_CODE.sub(_CODE_REPL, text)
    return text


# ── Shared streaming agentic loop ─────────────────────────────────────────────


@dataclass
class TurnCallbacks:
    """Callbacks injected by CLI / GUI to handle presentation during a turn.

    Every callback has a safe no-op default so callers only override what they need.
    """

    on_token: Callable[[str], None] = field(default=lambda: (lambda _t: None))
    on_tool_started: Callable[[list[str]], None] = field(default=lambda: (lambda _n: None))
    on_tool_finished: Callable[[str, str], None] = field(default=lambda: (lambda _n, _r: None))
    on_error: Callable[[str, str], None] = field(default=lambda: (lambda _c, _m: None))


def _create_llm_stream(
    llm: OpenAI,
    model: str,
    tools: list[dict],
    messages: list[dict],
    system_message: dict,
    callbacks: TurnCallbacks,
) -> object | None:
    """Open a streaming chat-completion request, mapping API errors to callbacks.

    Returns the raw stream iterator on success, or ``None`` if an API error
    occurred (the error callback is invoked before returning ``None``).
    """
    try:
        return llm.chat.completions.create(
            model=model,
            max_tokens=MAX_TOKENS,
            tools=tools,
            messages=[system_message] + messages,
            stream=True,
        )
    except openai.APITimeoutError as exc:
        callbacks.on_error("Timeout", f"LLM request timed out ({exc})")
    except openai.APIConnectionError as exc:
        callbacks.on_error("Connection", f"Cannot reach LLM endpoint: {exc}")
    except openai.AuthenticationError as exc:
        callbacks.on_error("Auth", f"Invalid API key: {exc}")
    except openai.APIStatusError as exc:
        callbacks.on_error("API", f"LLM error {exc.status_code}: {exc.message}")
    except openai.OpenAIError as exc:
        callbacks.on_error("LLM", f"LLM error: {exc}")
    return None


def _accumulate_stream_chunks(
    stream: object, callbacks: TurnCallbacks,
) -> tuple[str, list[dict], str | None]:
    """Consume a stream and return (content, tool_calls, finish_reason).

    Calls ``callbacks.on_token`` for every text chunk received.
    """
    content_parts: list[str]  = []
    tool_calls: list[dict]    = []
    finish_reason: str | None = None

    for chunk in stream:
        choice = chunk.choices[0] if chunk.choices else None
        if choice is None:
            continue
        delta = choice.delta

        if delta.content:
            content_parts.append(delta.content)
            callbacks.on_token(delta.content)

        if delta.tool_calls:
            for tc in delta.tool_calls:
                while len(tool_calls) <= tc.index:
                    tool_calls.append(
                        {"id": "", "function": {"name": "", "arguments": ""}}
                    )
                entry = tool_calls[tc.index]
                if tc.id:
                    entry["id"] = tc.id
                if tc.function and tc.function.name:
                    entry["function"]["name"] += tc.function.name
                if tc.function and tc.function.arguments:
                    entry["function"]["arguments"] += tc.function.arguments

        if choice.finish_reason:
            finish_reason = choice.finish_reason

    return "".join(content_parts), tool_calls, finish_reason


def _stream_llm_response(
    llm: OpenAI,
    model: str,
    tools: list[dict],
    messages: list[dict],
    system_message: dict,
    callbacks: TurnCallbacks,
) -> tuple[str, list[dict], str | None] | tuple[None, None, str]:
    """Open a streaming request and collect content + tool-call fragments.

    Returns ``(content, tool_calls, finish_reason)`` on success, or
    ``(None, None, "error")`` if an API error was raised (callback already invoked).
    """
    stream = _create_llm_stream(llm, model, tools, messages, system_message, callbacks)
    if stream is None:
        return None, None, "error"
    return _accumulate_stream_chunks(stream, callbacks)


def _execute_tool_calls(
    tool_calls: list[dict],
    content: str,
    pool: MCPClientPool,
    messages: list[dict],
    callbacks: TurnCallbacks,
    start_time: float,
) -> str | None:
    """Execute a batch of tool calls in parallel and append results to messages.

    Args:
        tool_calls: Assembled tool-call dicts from the streaming response.
        content: Any text content emitted alongside the tool calls (may be empty).
        pool: MCP client pool for parallel execution.
        messages: Mutable conversation history — assistant + tool msgs appended.
        callbacks: ``on_tool_started``, ``on_tool_finished``, ``on_error`` used.
        start_time: ``time.monotonic()`` value from the start of the turn.

    Returns:
        ``None`` on success (caller should continue the loop).
        ``"error"`` if tool execution failed (error callback already invoked).
    """
    messages.append({
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["function"]["name"],
                    "arguments": tc["function"]["arguments"],
                },
            }
            for tc in tool_calls
        ],
    })

    names = [tc["function"]["name"] for tc in tool_calls]
    callbacks.on_tool_started(names)

    try:
        results = pool.call_tools_parallel(tool_calls)
    except RuntimeError as exc:
        callbacks.on_error("MCP", f"MCP server crashed or closed: {exc}")
        return "error"
    except Exception as exc:
        callbacks.on_error("Tool", f"Tool execution failed: {exc}")
        return "error"

    for tc_id, name, result in results:
        messages.append({
            "role": "tool",
            "tool_call_id": tc_id,
            "content": result,
        })
        callbacks.on_tool_finished(name, result)

    return None  # continue loop


def _handle_finish_reason(
    finish_reason: str | None,
    content: str,
    tool_calls: list,
    pool: MCPClientPool,
    messages: list[dict],
    callbacks: TurnCallbacks,
    start_time: float,
) -> tuple[str, float] | None:
    """Dispatch on *finish_reason* and return a result tuple, or ``None`` to continue.

    Returns:
        ``(reason, elapsed)`` if the turn is complete, or ``None`` if the
        agentic loop should continue with the next round.
    """
    elapsed = time.monotonic() - start_time

    if finish_reason == "error":
        return "error", elapsed

    if finish_reason in ("stop", None) and not tool_calls:
        messages.append({"role": "assistant", "content": content})
        return finish_reason or "stop", elapsed

    if finish_reason == "tool_calls":
        err = _execute_tool_calls(
            tool_calls, content, pool, messages, callbacks, start_time,
        )
        if err == "error":
            return "error", time.monotonic() - start_time
        return None  # continue loop

    # max_tokens, content_filter, etc.
    messages.append({"role": "assistant", "content": content})
    return finish_reason or "unknown", elapsed


def run_streaming_turn(
    llm: OpenAI,
    pool: MCPClientPool,
    tools: list[dict],
    system_message: dict,
    messages: list[dict],
    model: str,
    callbacks: TurnCallbacks,
) -> tuple[str, float]:
    """Run one user-turn: stream response, execute tool calls, repeat.

    This is the shared core loop used by both the CLI and GUI. Presentation
    concerns (spinners, colours, Qt signals) are handled by the *callbacks*.

    Args:
        llm: OpenAI-compatible client.
        pool: MCP client pool for tool execution.
        tools: Tool definitions in OpenAI format.
        system_message: Pre-built ``{"role": "system", ...}`` dict.
        messages: Mutable conversation history — modified in-place.
        model: Model identifier string.
        callbacks: Presentation callbacks.

    Returns:
        A ``(finish_reason, elapsed_seconds)`` tuple.  *finish_reason* is the
        last value from the streaming API (``"stop"``, ``"tool_calls"``,
        ``"length"``, etc.) or ``"error"`` if an exception was raised.
    """
    start_time = time.monotonic()

    for _round in range(MAX_TOOL_ROUNDS):
        messages[:] = prune_history(messages)

        content, tool_calls, finish_reason = _stream_llm_response(
            llm, model, tools, messages, system_message, callbacks,
        )

        result = _handle_finish_reason(
            finish_reason, content, tool_calls,
            pool, messages, callbacks, start_time,
        )
        if result is not None:
            return result

    # Loop exhausted MAX_TOOL_ROUNDS without a terminal finish_reason.
    callbacks.on_error(
        "Loop", f"Exceeded {MAX_TOOL_ROUNDS} tool-call rounds — aborting turn"
    )
    return "error", time.monotonic() - start_time

