#!/usr/bin/env python3
"""
SysControl Agent — Core utilities.

Provides the MCP client, client pool, and shared helpers used by both the
CLI (agent/cli.py) and the Swift bridge (agent/bridge.py).
"""

import base64
import binascii
import collections
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
from typing import IO, Any, cast

try:
    import fcntl as fcntl_mod  # noqa: F401 — re-exported for cli.py / server.py
    HAS_FCNTL = True
except ImportError:
    fcntl_mod = None  # type: ignore[assignment]  # noqa: F401
    HAS_FCNTL = False

import openai
from openai import OpenAI, Stream  # noqa: F401 — re-exported for downstream imports
from openai.types.chat import ChatCompletionChunk

from agent.paths import MEMORY_FILE, PROMPT_PATH, SERVER_PATH  # frozen-app-aware paths

# ── Shared constants ─────────────────────────────────────────────────────────

EXIT_PHRASES: frozenset[str] = frozenset({
    "exit", "quit", "bye", "goodbye", "good bye", "farewell",
    "see ya", "see you", "cya", "later", "take care", "peace",
    "done", "close", "end", "stop", ":q", "q", "adios", "adieu",
    "ttyl", "ttfn", "night", "goodnight", "good night",
})

MAX_HISTORY_MESSAGES = 40  # ~20 user turns; keeps context within model limits

# OpenAI client tuning — env-controllable for slow networks / cloud environments.
_LLM_TIMEOUT_DEFAULT = 120.0
_LLM_MAX_RETRIES_DEFAULT = 2


def llm_client_timeout() -> float:
    """Return the OpenAI client timeout in seconds.

    Reads ``SYSCONTROL_LLM_TIMEOUT`` from the environment; falls back to
    ``120.0`` if unset or unparseable.
    """
    raw = os.environ.get("SYSCONTROL_LLM_TIMEOUT", "")
    try:
        value = float(raw)
        return value if value > 0 else _LLM_TIMEOUT_DEFAULT
    except ValueError:
        return _LLM_TIMEOUT_DEFAULT


def llm_client_max_retries() -> int:
    """Return the OpenAI client max retries (env: ``SYSCONTROL_LLM_MAX_RETRIES``)."""
    raw = os.environ.get("SYSCONTROL_LLM_MAX_RETRIES", "")
    try:
        value = int(raw)
        return value if value >= 0 else _LLM_MAX_RETRIES_DEFAULT
    except ValueError:
        return _LLM_MAX_RETRIES_DEFAULT

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_TOKENS         = 16384
POOL_SIZE          = 4          # max parallel MCP worker processes
MAX_PARALLEL_TOOLS = POOL_SIZE  # batch size capped to pool capacity
MAX_TOOL_ROUNDS    = 15         # circuit-breaker for runaway tool-call loops
_MAX_CHART_BYTES   = 10 * 1024 * 1024  # Backward-compatible alias.
_MAX_ARTIFACT_BYTES = 25 * 1024 * 1024  # 25 MB cap on decoded visual artifacts
_CHART_FILE_PREFIX = "syscontrol_chart_"
_ARTIFACT_FILE_PREFIX = "syscontrol_artifact_"
_IMAGE_TOOL_NAME = "generate_image"
_IMAGE_MODEL_DEFAULT = "gpt-image-1"
_IMAGE_SIZE_VALUES = {"1024x1024", "1024x1536", "1536x1024", "auto"}
ToolApprover = Callable[[str, dict], bool]

RESPONSE_STYLE_GUIDANCE: str = (
    "\n\n---\n\n# Response Style\n\n"
    "When replying to the user:\n"
    "- Sound conversational, warm, and capable, like a helpful AI assistant rather than a diagnostic report.\n"
    "- Treat vague requests as collaboration: ask one concise follow-up when the missing detail materially changes the outcome.\n"
    "- When the next step is low-risk and obvious, make a reasonable assumption, say what you assumed, and proceed.\n"
    "- Anticipate what would make the answer more useful: include comparisons, next actions, or visual summaries when they clarify the result.\n"
    "- Use chart-returning tools proactively when a visualization would help the user understand performance, trends, proportions, or tradeoffs.\n"
    "- Avoid a single dense paragraph for non-trivial answers.\n"
    "- Prefer a short direct lead, then concise bullets or numbered steps when helpful.\n"
    "- Prefer headings + bullet lists over markdown tables unless the user explicitly asks for a table.\n"
    "- Insert blank lines between sections so responses are easy to scan.\n"
    "- Use markdown structure naturally (headings, bullets, code blocks) when it improves clarity.\n"
    "- End with a natural follow-up or offer only when it advances the user's likely next step; do not tack one on mechanically.\n"
    "- Keep simple requests short (1-2 sentences).\n"
    "- For actionable instructions, provide concrete commands/examples.\n"
)

# ── Provider config ───────────────────────────────────────────────────────────

OLLAMA_CLOUD_MODEL    = "gpt-oss:120b"
OLLAMA_CLOUD_BASE_URL = "https://ollama.com/v1"

# Backward-compatible aliases for older call sites/imports.  These still point
# to Ollama Cloud; "OpenAI" only describes the compatible HTTP protocol/client.
CLOUD_MODEL    = OLLAMA_CLOUD_MODEL
CLOUD_BASE_URL = OLLAMA_CLOUD_BASE_URL

LOCAL_MODEL    = "qwen3:30b"  # any model pulled via: ollama pull <model>
LOCAL_BASE_URL = "http://localhost:11434/v1"
LOCAL_API_KEY  = "ollama"   # Ollama doesn't require a real key
LOCAL_TAGS_URL_FALLBACK = "http://localhost:11434/api/tags"


def _field(obj: Any, name: str) -> Any:
    """Read a field from an SDK object or dict without caring which it is."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _write_b64_image_artifact(
    img_data: str,
    tracked_files: list[str],
    mime_type: str = "image/png",
) -> tuple[str | None, str | None]:
    """Decode a base64 image, save it to temp, and track it for cleanup."""
    if not img_data:
        return None, "missing image data"
    try:
        decoded = base64.b64decode(img_data, validate=True)
    except (binascii.Error, ValueError):
        return None, "decode error"
    if len(decoded) > _MAX_ARTIFACT_BYTES:
        return None, "exceeds size limit"

    ext = ".png"
    if mime_type == "image/jpeg":
        ext = ".jpg"
    elif mime_type == "image/webp":
        ext = ".webp"

    digest = hashlib.md5(img_data[:64].encode()).hexdigest()[:10]  # noqa: S324
    path = os.path.join(
        tempfile.gettempdir(),
        f"{_ARTIFACT_FILE_PREFIX}{digest}{ext}",
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(decoded)
    tracked_files.append(path)
    return path, None


def _format_tool_result_with_image(
    data: dict,
    img_b64: str,
    tracked_files: list[str],
    mime_type: str = "image/png",
) -> str:
    """Return JSON text plus the legacy inline-image marker consumed by the GUI."""
    parts = [json.dumps(data, indent=2)]
    if img_b64:
        path, error = _write_b64_image_artifact(img_b64, tracked_files, mime_type)
        if path:
            parts.append(f"\n[chart_image:{path}]")
        else:
            parts.append(f"[visual artifact: {error}]")
    return "\n".join(parts)


def _image_api_config(
    provider_api_key: str | None,
    provider_base_url: str | None,
) -> tuple[str | None, str | None, str]:
    """Resolve the API credentials used by the image-generation tool."""
    image_key = os.environ.get("SYSCONTROL_IMAGE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    image_base = os.environ.get("SYSCONTROL_IMAGE_BASE_URL")
    if image_key:
        return image_key, image_base, "image_env"

    api_key = (provider_api_key or "").strip()
    base_url = (provider_base_url or "").strip().rstrip("/")
    if api_key and api_key != "ollama" and "api.openai.com" in base_url:
        return api_key, base_url, "configured_openai_provider"

    return None, None, "missing"


def _image_generation_request(args: dict) -> dict:
    """Normalize LLM-supplied image generation arguments."""
    prompt = str(args.get("prompt", "")).strip()
    model = str(args.get("model") or _IMAGE_MODEL_DEFAULT).strip()
    size = str(args.get("size") or "1024x1024").strip()
    quality = str(args.get("quality") or "auto").strip()
    background = str(args.get("background") or "auto").strip()

    if size not in _IMAGE_SIZE_VALUES:
        size = "1024x1024"

    request: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": size,
    }
    if quality:
        request["quality"] = quality
    if background and background != "auto":
        request["background"] = background
    return request


def _call_generate_image_tool(
    args: dict,
    provider_api_key: str | None,
    provider_base_url: str | None,
    tracked_files: list[str],
) -> str:
    """Generate an image with OpenAI Images and return a GUI-renderable result."""
    request = _image_generation_request(args)
    prompt = request.get("prompt", "")
    if not prompt:
        return json.dumps({"error": "prompt is required."}, indent=2)

    api_key, base_url, source = _image_api_config(provider_api_key, provider_base_url)
    if not api_key:
        return json.dumps({
            "error": "No OpenAI image API key is configured.",
            "hint": (
                "Set OPENAI_API_KEY or SYSCONTROL_IMAGE_API_KEY, or configure "
                "SysControl with an OpenAI base URL so generated images can be created."
            ),
        }, indent=2)

    client_kwargs: dict[str, Any] = {
        "api_key": api_key,
        "timeout": llm_client_timeout(),
        "max_retries": llm_client_max_retries(),
    }
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)

    try:
        response = client.images.generate(**request)
    except TypeError:
        request.pop("background", None)
        try:
            response = client.images.generate(**request)
        except openai.OpenAIError as exc:
            return json.dumps({"error": f"Image generation failed: {exc}"}, indent=2)
    except openai.OpenAIError as exc:
        return json.dumps({"error": f"Image generation failed: {exc}"}, indent=2)

    items = _field(response, "data") or []
    first = items[0] if items else None
    img_b64 = _field(first, "b64_json") if first is not None else None
    revised_prompt = _field(first, "revised_prompt") if first is not None else None
    if not img_b64:
        url = _field(first, "url") if first is not None else None
        if url:
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    img_b64 = base64.b64encode(r.read()).decode()
            except Exception as exc:
                return json.dumps({"error": f"Could not fetch generated image URL: {exc}"}, indent=2)
    if not img_b64:
        return json.dumps({"error": "Image generation returned no image data."}, indent=2)

    meta = {
        "status": "ok",
        "model": request["model"],
        "size": request["size"],
        "quality": request.get("quality"),
        "background": request.get("background", "auto"),
        "credential_source": source,
    }
    if revised_prompt:
        meta["revised_prompt"] = revised_prompt
    return _format_tool_result_with_image(meta, img_b64, tracked_files)

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

_STDERR_MAX_BYTES = 4096  # cap stderr buffer size


class MCPClient:
    """Minimal JSON-RPC client that talks to mcp/server.py over stdio."""

    def __init__(self, extra_env: dict[str, str] | None = None) -> None:
        """Spawn the MCP server subprocess and perform the JSON-RPC handshake.

        Args:
            extra_env: Optional complete environment dict for the subprocess.
                When provided, it **replaces** the parent environment entirely —
                callers are responsible for including any vars the server
                requires (PATH, HOME, etc.).  This keeps secret-isolation
                guarantees from ``runner._build_subprocess_env()`` intact.
                When ``None``, the subprocess inherits the full parent env.

        Raises:
            RuntimeError: If the subprocess fails to start or the handshake
                times out / returns an unexpected response.
        """
        # In a frozen PyInstaller bundle, sys.executable points to the app
        # binary, not a Python interpreter. Re-invoke with --mcp-server so
        # the app entry-point can dispatch correctly.
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--mcp-server"]
        else:
            cmd = [sys.executable, str(SERVER_PATH)]

        proc_env = dict(extra_env) if extra_env is not None else None

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=proc_env,
        )
        # Narrow the Popen stdin/stdout types once and store as non-Optional
        # attributes, so each call site doesn't have to re-assert.
        assert self.proc.stdin is not None, "Popen stdin must be a pipe"
        assert self.proc.stdout is not None, "Popen stdout must be a pipe"
        self._stdin: IO[str] = self.proc.stdin
        self._stdout: IO[str] = self.proc.stdout
        self._id   = 0
        self._lock = threading.Lock()   # serialise writes/reads on this pipe
        self._chart_files: list[str] = []
        # A daemon thread drains stderr into a ring buffer.  Without this, a
        # chatty server can fill the ~64 KB pipe and deadlock its own writes,
        # hanging the parent's next readline().
        self._stderr_lines: collections.deque[str] = collections.deque(maxlen=200)
        self._stderr_lock = threading.Lock()
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr, daemon=True,
            name=f"mcp-stderr-drain-{self.proc.pid}",
        )
        self._stderr_thread.start()
        try:
            self._initialize()
        except Exception:
            # Tear down the subprocess so the drainer exits and we don't leak
            # a hung child if the handshake never completes.
            self.close()
            raise

    def _drain_stderr(self) -> None:
        """Read the server's stderr line-by-line until EOF, into a ring buffer."""
        pipe = self.proc.stderr
        if pipe is None:
            return
        try:
            for line in iter(pipe.readline, ""):
                with self._stderr_lock:
                    self._stderr_lines.append(line.rstrip("\n"))
        except (OSError, ValueError):
            pass

    def _last_stderr(self, max_chars: int = _STDERR_MAX_BYTES) -> str:
        """Return up to *max_chars* of the most recent stderr output."""
        with self._stderr_lock:
            text = "\n".join(self._stderr_lines).strip()
        if len(text) > max_chars:
            return text[-max_chars:]
        return text

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
                self._stdin.write(json.dumps(msg) + "\n")
                self._stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                err = self._last_stderr()
                raise RuntimeError(
                    f"MCP server crashed."
                    f"{(' Server error: ' + err) if err else ''}"
                ) from exc

            # Gate the blocking readline() behind select() when a timeout is
            # requested, so callers (e.g. _initialize) cannot hang forever.
            if _read_timeout is not None:
                try:
                    ready, _, _ = select.select(
                        [self._stdout], [], [], _read_timeout,
                    )
                except (ValueError, OSError):
                    ready = []
                if not ready:
                    raise TimeoutError(
                        f"MCP server did not respond to '{method}' within "
                        f"{_read_timeout:.1f}s — is mcp/server.py healthy?"
                    )

            raw = self._stdout.readline()
            if not raw:
                err = self._last_stderr()
                raise RuntimeError(
                    f"MCP server closed unexpectedly."
                    f"{(' Server error: ' + err) if err else ''}"
                )
            try:
                response: dict = json.loads(raw)
                return response
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"MCP server sent malformed JSON: {raw[:200]!r}"
                ) from exc

    def _notify(self, method: str) -> None:
        with self._lock:
            msg = {"jsonrpc": "2.0", "method": method}
            try:
                self._stdin.write(json.dumps(msg) + "\n")
                self._stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                err = self._last_stderr()
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
            err = self._last_stderr()
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
        tools: list[dict] = resp.get("result", {}).get("tools", [])
        return tools

    def call_tool(self, name: str, arguments: dict | None = None) -> str:
        """Execute a tool by name and return the text result.

        When the tool produces an image (chart, screenshot, generated artifact),
        the image is saved to a temp file and a ``[chart_image:/path]`` marker
        is appended. Temp files are tracked and cleaned up by ``close()``.

        Args:
            name: MCP tool name to invoke.
            arguments: Tool arguments dict, or ``None`` for no arguments.

        Returns:
            Combined text content from the tool, with inline image markers
            appended for any image content items.
        """
        resp = self._send("tools/call", {"name": name, "arguments": arguments or {}})
        if "error" in resp:
            err = resp["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            return f"[tool error: {msg}]"
        content = resp.get("result", {}).get("content", [])
        if not content:
            return "[no content returned]"

        text_parts: list[str] = []
        for item in content:
            if item.get("type") == "text":
                text_parts.append(item.get("text", ""))
            elif item.get("type") == "image":
                img_data = item.get("data", "")
                mime_type = item.get("mimeType", "image/png")
                path, error = _write_b64_image_artifact(
                    img_data, self._chart_files, mime_type,
                )
                if path:
                    text_parts.append(f"\n[chart_image:{path}]")
                elif error:
                    text_parts.append(f"[visual artifact: {error}]")

        return "\n".join(text_parts) if text_parts else "[no content returned]"

    def close(self) -> None:
        """Gracefully shut down the subprocess: close stdin → terminate → kill.

        Each step is guarded so a failure at any stage does not prevent the
        next attempt.  A final ``wait()`` confirms the process is reaped.
        Chart temp files created by ``call_tool()`` are cleaned up here.
        Stdout/stderr are closed before termination so the server is not left
        blocked on a full pipe buffer.
        """
        # Clean up visual-artifact temp files
        for path in self._chart_files:
            with contextlib.suppress(OSError):
                os.remove(path)
        self._chart_files.clear()

        pid = self.proc.pid

        # Close stdin first so the server sees EOF on its read loop, then
        # close stdout to unblock any pending server write.
        with contextlib.suppress(Exception):
            self._stdin.close()
        with contextlib.suppress(Exception):
            self._stdout.close()

        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(Exception):
                self.proc.kill()
                self.proc.wait(timeout=2)
        except Exception as exc:
            sys.stderr.write(
                f"[syscontrol] MCPClient.close terminate (pid={pid}): {exc}\n"
            )
            with contextlib.suppress(Exception):
                self.proc.kill()
                self.proc.wait(timeout=2)

        # Drainer thread will exit on stderr EOF.  Join briefly to reap it.
        with contextlib.suppress(Exception):
            self._stderr_thread.join(timeout=1.0)


# ── MCP Client Pool ───────────────────────────────────────────────────────────


def _parse_tool_call_args(tc: dict) -> tuple[str, dict]:
    """Extract tool name and parsed arguments from a tool-call dict.

    Args:
        tc: An OpenAI-format tool-call dict with ``function.name`` and
            ``function.arguments`` keys.

    Returns:
        A ``(name, args)`` tuple.

    Raises:
        ValueError: If the tool name or argument payload is malformed.
    """
    fn = tc.get("function") or {}
    name = str(fn.get("name", "")).strip()
    if not name:
        raise ValueError("LLM returned a tool call without a function name.")

    raw_args = fn.get("arguments", "{}")
    if raw_args in (None, ""):
        return name, {}
    if isinstance(raw_args, dict):
        return name, raw_args
    if not isinstance(raw_args, str):
        raise ValueError(
            f"Tool call '{name}' arguments must be a JSON object string."
        )

    try:
        args = json.loads(raw_args)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Tool call '{name}' arguments were not valid JSON: {exc.msg}."
        ) from exc
    if not isinstance(args, dict):
        raise ValueError(f"Tool call '{name}' arguments must decode to a JSON object.")
    return name, args


class MCPClientPool:
    """
    Manages a pool of MCPClient instances so independent tool calls can be
    executed concurrently — each call gets its own subprocess/pipe.

    Workers are lazily initialised: the primary client is created eagerly and
    extras are spawned only when a parallel batch actually needs them.
    """

    def __init__(
        self,
        primary: MCPClient,
        pool_size: int = POOL_SIZE,
        provider_api_key: str | None = None,
        provider_base_url: str | None = None,
        tool_approver: ToolApprover | None = None,
    ) -> None:
        """Initialise the pool with a pre-created primary client.

        Args:
            primary: The eagerly-created MCP client placed at index 0.
                The pool takes ownership and will close it on ``close_all()``.
            pool_size: Maximum number of concurrent MCP clients.  Extra clients
                are spawned lazily when a parallel batch actually needs them.
        """
        self._clients: dict[int, MCPClient] = {0: primary}
        self._pool_size = pool_size
        self._pool_lock = threading.Lock()  # guards _clients and _slot_locks
        # Per-slot locks let two threads spawning different slots proceed in
        # parallel, while two threads racing on the same slot serialise so
        # only one MCPClient is created.
        self._slot_locks: dict[int, threading.Lock] = {}
        self._parallel_safe: frozenset[str] | None = None  # lazily populated
        self._provider_api_key = provider_api_key
        self._provider_base_url = provider_base_url
        self._tool_approver = tool_approver

    def set_provider_config(self, api_key: str | None, base_url: str | None) -> None:
        """Update provider details for native tools that need configured credentials."""
        self._provider_api_key = api_key
        self._provider_base_url = base_url

    def set_tool_approver(self, approver: ToolApprover | None) -> None:
        """Update the optional per-tool approval hook used by interactive clients."""
        self._tool_approver = approver

    def _call_tool(self, name: str, args: dict, client: MCPClient) -> str:
        if self._tool_approver is not None and not self._tool_approver(name, args):
            return (
                "[tool denied: the CLI approval policy blocked this call. "
                "Explain what you would do instead, or ask the user to change modes.]"
            )
        if name == _IMAGE_TOOL_NAME:
            return _call_generate_image_tool(
                args,
                self._provider_api_key,
                self._provider_base_url,
                client._chart_files,
            )
        return client.call_tool(name, args)

    def _get_or_create(self, index: int) -> MCPClient:
        assert 0 <= index < self._pool_size, (
            f"Pool index {index} out of range [0, {self._pool_size})"
        )

        # Fast path — already created.
        with self._pool_lock:
            if index in self._clients:
                return self._clients[index]
            slot_lock = self._slot_locks.setdefault(index, threading.Lock())

        # Slow path — spawn under a per-slot lock so concurrent callers for
        # the same index serialise without blocking other indexes.
        with slot_lock:
            with self._pool_lock:
                if index in self._clients:
                    return self._clients[index]
            new_client = MCPClient()
            with self._pool_lock:
                self._clients[index] = new_client
                return new_client

    def warm_up(self, count: int | None = None) -> None:
        """Pre-spawn worker clients in background threads.

        Args:
            count: Number of workers to spawn.  Defaults to ``pool_size - 1``
                (all workers besides the primary).
        """
        target = min(count or (self._pool_size - 1), self._pool_size - 1)
        threads: list[threading.Thread] = []
        for i in range(1, target + 1):
            with self._pool_lock:
                if i in self._clients:
                    continue
            t = threading.Thread(
                target=self._get_or_create, args=(i,), daemon=True,
            )
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

    # Sentinel: distinguishes "server unreachable, allow everything" from a
    # legitimately loaded (but possibly empty) set of safe tool names.
    _FALLBACK: frozenset[str] = frozenset()

    def _get_parallel_safe(self) -> frozenset[str]:
        """Return the set of tool names that are safe to run concurrently.

        Lazily fetches the tool list from the primary MCP client on first call
        and caches it for the lifetime of the pool.
        """
        if self._parallel_safe is None:
            try:
                tools = self._clients[0].list_tools()  # primary always at index 0
                self._parallel_safe = frozenset(
                    t["name"] for t in tools if t.get("parallel", True)
                )
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
            result = self._call_tool(name, args, self._clients[0])  # primary client
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
            return (order, tc["id"], name, self._call_tool(name, args, client))

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
    prompt: str = data["system_prompt"]["prompt"]
    return prompt


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


_MEMORY_HINT = (
    "\n\n---\n\n# Memory\n\n"
    "A persistent memory file exists with notes from past sessions. "
    "Call `read_memory` when the user references something from a previous session, "
    "asks what you remember, or when prior context seems relevant. "
    "Call `append_memory_note` to save a key fact mid-session without waiting for exit."
)


def build_full_system_prompt(base_prompt: str, tool_names: list[str]) -> str:
    """Assemble the complete system prompt sent to the LLM.

    Combines the static base prompt, a runtime-derived list of available tool
    names, an optional memory-file hint when ``SysControl_Memory.md`` exists,
    and the response-style guidance.  Used by both the CLI and Swift bridge so
    they stay behaviourally identical.
    """
    tool_list_block = (
        "\n\n---\n\n# Available Tools\n\n"
        "You have access to the following tools (call them by name):\n"
        + "\n".join(f"- {n}" for n in tool_names)
    )
    full = base_prompt + tool_list_block
    if load_memory() is not None:
        full += _MEMORY_HINT
    full += RESPONSE_STYLE_GUIDANCE
    return full


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


def ollama_tags_url(base_url: str = LOCAL_BASE_URL) -> str:
    """Derive Ollama /api/tags endpoint from an OpenAI-compatible base URL."""
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        return LOCAL_TAGS_URL_FALLBACK
    if normalized.lower().endswith("/v1"):
        normalized = normalized[:-3]
    return f"{normalized}/api/tags"


def fetch_ollama_models(base_url: str = LOCAL_BASE_URL) -> list[str]:
    """Return sorted list of locally installed Ollama model names.

    Returns an empty list if Ollama is not running or unreachable (3 s timeout).
    """
    try:
        tags_url = ollama_tags_url(base_url)
        req = urllib.request.Request(
            tags_url,
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

    on_token: Callable[[str], None] = field(default_factory=lambda: lambda _t: None)
    on_tool_started: Callable[[list[str]], None] = field(default_factory=lambda: lambda _n: None)
    on_tool_finished: Callable[[str, str], None] = field(default_factory=lambda: lambda _n, _r: None)
    on_error: Callable[[str, str], None] = field(default_factory=lambda: lambda _c, _m: None)
    cancel_event: threading.Event | None = field(default=None)


def _create_llm_stream(
    llm: OpenAI,
    model: str,
    tools: list[dict],
    messages: list[dict],
    system_message: dict,
    callbacks: TurnCallbacks,
) -> Stream[ChatCompletionChunk] | None:
    """Open a streaming chat-completion request, mapping API errors to callbacks.

    Returns the raw stream iterator on success, or ``None`` if an API error
    occurred (the error callback is invoked before returning ``None``).
    """
    try:
        # The OpenAI SDK overloads chat.completions.create — when ``stream=True``
        # the return type is ``Stream[ChatCompletionChunk]`` but mypy doesn't
        # always pick up the overload through keyword arguments.  Cast it.
        return cast(
            "Stream[ChatCompletionChunk]",
            llm.chat.completions.create(
                model=model,
                max_tokens=MAX_TOKENS,
                tools=tools,  # type: ignore[arg-type]
                messages=[system_message, *messages],  # type: ignore[list-item]
                stream=True,
            ),
        )
    except openai.OpenAIError as exc:
        _report_llm_error(exc, callbacks, "request")
    return None


def _report_llm_error(exc: Exception, callbacks: TurnCallbacks, phase: str) -> None:
    """Map SDK/network errors to stable UI-facing error categories."""
    if isinstance(exc, openai.APITimeoutError):
        callbacks.on_error("Timeout", f"LLM {phase} timed out ({exc})")
    elif isinstance(exc, openai.APIConnectionError):
        callbacks.on_error("Connection", f"Cannot reach LLM endpoint during {phase}: {exc}")
    elif isinstance(exc, openai.AuthenticationError):
        callbacks.on_error("Auth", f"Invalid API key: {exc}")
    elif isinstance(exc, openai.APIStatusError):
        callbacks.on_error("API", f"LLM error {exc.status_code}: {exc.message}")
    elif isinstance(exc, openai.OpenAIError):
        callbacks.on_error("LLM", f"LLM {phase} error: {exc}")
    else:
        callbacks.on_error("LLM", f"LLM {phase} failed: {exc}")


def _accumulate_stream_chunks(
    stream: Stream[ChatCompletionChunk], callbacks: TurnCallbacks,
) -> tuple[str, list[dict], str | None] | tuple[None, None, str]:
    """Consume a stream and return (content, tool_calls, finish_reason).

    Calls ``callbacks.on_token`` for every text chunk received.
    """
    content_parts: list[str]  = []
    tool_calls: list[dict]    = []
    finish_reason: str | None = None

    try:
        for chunk in stream:
            if callbacks.cancel_event and callbacks.cancel_event.is_set():
                with contextlib.suppress(Exception):
                    stream.close()
                return "".join(content_parts), tool_calls, "cancelled"

            choice = chunk.choices[0] if chunk.choices else None
            if choice is None:
                continue
            delta = choice.delta

            if delta.content:
                content_parts.append(delta.content)
                callbacks.on_token(delta.content)

            if delta.tool_calls:
                for fallback_index, tc in enumerate(delta.tool_calls):
                    index = tc.index if tc.index is not None else fallback_index
                    while len(tool_calls) <= index:
                        tool_calls.append(
                            {"id": "", "function": {"name": "", "arguments": ""}}
                        )
                    entry = tool_calls[index]
                    if tc.id:
                        entry["id"] = tc.id
                    if tc.function and tc.function.name:
                        entry["function"]["name"] += tc.function.name
                    if tc.function and tc.function.arguments:
                        entry["function"]["arguments"] += tc.function.arguments

            if choice.finish_reason:
                finish_reason = choice.finish_reason
    except Exception as exc:
        with contextlib.suppress(Exception):
            stream.close()
        _report_llm_error(exc, callbacks, "stream")
        return None, None, "error"

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


def _prepare_tool_calls(tool_calls: list[dict], callbacks: TurnCallbacks) -> list[dict] | None:
    """Validate and normalize streamed tool calls before appending/executing them."""
    prepared: list[dict] = []
    for index, tc in enumerate(tool_calls):
        try:
            name, args = _parse_tool_call_args(tc)
        except ValueError as exc:
            callbacks.on_error("Tool", str(exc))
            return None

        arguments = json.dumps(args, separators=(",", ":"))
        call_id = str(tc.get("id") or "").strip()
        if not call_id:
            digest = hashlib.md5(f"{index}:{name}:{arguments}".encode()).hexdigest()[:8]  # noqa: S324
            call_id = f"call_{index}_{digest}"
        prepared.append({
            "id": call_id,
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments,
            },
        })
    return prepared


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
    prepared = _prepare_tool_calls(tool_calls, callbacks)
    if prepared is None:
        return "error"

    messages.append({
        "role": "assistant",
        "content": content or None,
        "tool_calls": prepared,
    })

    names = [tc["function"]["name"] for tc in prepared]
    callbacks.on_tool_started(names)

    try:
        results = pool.call_tools_parallel(prepared)
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

    if finish_reason == "cancelled":
        if content:
            messages.append({"role": "assistant", "content": content})
        return "cancelled", elapsed

    if tool_calls:
        err = _execute_tool_calls(
            tool_calls, content, pool, messages, callbacks, start_time,
        )
        if err == "error":
            return "error", time.monotonic() - start_time
        return None  # continue loop

    if finish_reason == "tool_calls":
        callbacks.on_error("LLM", "LLM indicated tool calls but did not send any tool calls.")
        return "error", elapsed

    if finish_reason in ("stop", None):
        messages.append({"role": "assistant", "content": content})
        return finish_reason or "stop", elapsed

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
    max_rounds: int | None = None,
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
        max_rounds: Optional override for the per-turn tool-call round cap.
            Defaults to ``MAX_TOOL_ROUNDS``.  Used by sub-agents to honour
            their per-spec ``max_rounds`` budget.

    Returns:
        A ``(finish_reason, elapsed_seconds)`` tuple.  *finish_reason* is the
        last value from the streaming API (``"stop"``, ``"tool_calls"``,
        ``"length"``, etc.) or ``"error"`` if an exception was raised.
    """
    start_time = time.monotonic()
    rounds = max_rounds if max_rounds is not None else MAX_TOOL_ROUNDS

    for _round in range(rounds):
        if callbacks.cancel_event and callbacks.cancel_event.is_set():
            return "cancelled", time.monotonic() - start_time

        messages[:] = prune_history(messages)

        content, tool_calls, finish_reason = _stream_llm_response(
            llm, model, tools, messages, system_message, callbacks,
        )

        # _stream_llm_response signals API failure with (None, None, "error").
        # Bail out immediately rather than passing None into _handle_finish_reason.
        if content is None or tool_calls is None:
            return "error", time.monotonic() - start_time

        result = _handle_finish_reason(
            finish_reason, content, tool_calls,
            pool, messages, callbacks, start_time,
        )
        if result is not None:
            return result

    # Loop exhausted the round budget without a terminal finish_reason.
    callbacks.on_error(
        "Loop", f"Exceeded {rounds} tool-call rounds — aborting turn"
    )
    return "error", time.monotonic() - start_time
