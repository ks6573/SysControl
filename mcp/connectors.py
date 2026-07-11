"""External stdio MCP connector registry and process manager.

Connectors are explicitly configured, disabled by default at the product
permission layer, launched without a shell, and receive a minimal environment.
Their tools are namespaced as ``<connector>__<tool>`` to avoid collisions with
built-ins and with one another.
"""

from __future__ import annotations

import collections
import contextlib
import json
import os
import re
import subprocess
import threading
from collections.abc import Iterable
from typing import Any, TypedDict

from agent.paths import CONNECTORS_FILE, ensure_user_data_dir

MAX_CONNECTORS = 20
MAX_ARGS = 40
_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_ENV_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,79}$")


class ConnectorConfig(TypedDict):
    name: str
    command: str
    args: list[str]
    inherit_env: list[str]
    enabled: bool


def _read_configs() -> list[dict[str, Any]]:
    try:
        loaded = json.loads(CONNECTORS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    return loaded if isinstance(loaded, list) else []


def _write_configs(configs: list[dict[str, Any]]) -> None:
    ensure_user_data_dir()
    temporary = CONNECTORS_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(configs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(CONNECTORS_FILE)


def validate_config(
    name: str,
    command: str,
    args: Iterable[str] = (),
    inherit_env: Iterable[str] = (),
    *,
    enabled: bool = True,
) -> ConnectorConfig:
    """Validate and normalize an external MCP connector configuration."""
    normalized_name = name.strip().lower()
    if not _NAME_RE.fullmatch(normalized_name):
        raise ValueError("connector name must use lowercase letters, digits, '-' or '_'")
    normalized_command = command.strip()
    if not normalized_command or "\x00" in normalized_command:
        raise ValueError("connector command must be one executable path or name")
    if isinstance(args, (str, bytes)) or isinstance(inherit_env, (str, bytes)):
        raise ValueError("connector args and inherit_env must be arrays")
    normalized_args = [str(value) for value in args]
    if len(normalized_args) > MAX_ARGS or any(len(value) > 4096 for value in normalized_args):
        raise ValueError(f"connector args are limited to {MAX_ARGS} values of 4096 characters")
    normalized_env = sorted({str(value).strip() for value in inherit_env if str(value).strip()})
    if any(not _ENV_RE.fullmatch(value) for value in normalized_env):
        raise ValueError("inherit_env values must be uppercase environment variable names")
    return {
        "name": normalized_name,
        "command": normalized_command,
        "args": normalized_args,
        "inherit_env": normalized_env,
        "enabled": bool(enabled),
    }


def list_configs() -> list[ConnectorConfig]:
    """Return valid persisted connector configurations."""
    configs: list[ConnectorConfig] = []
    for value in _read_configs():
        try:
            configs.append(validate_config(
                str(value.get("name", "")), str(value.get("command", "")),
                value.get("args", []), value.get("inherit_env", []),
                enabled=bool(value.get("enabled", True)),
            ))
        except (TypeError, ValueError):
            continue
    return configs


def add_config(config: ConnectorConfig) -> ConnectorConfig:
    """Add or replace a connector configuration by name."""
    configs = list_configs()
    survivors = [item for item in configs if item["name"] != config["name"]]
    if len(survivors) >= MAX_CONNECTORS:
        raise ValueError(f"connector limit reached ({MAX_CONNECTORS})")
    survivors.append(config)
    _write_configs([dict(item) for item in survivors])
    return config


def remove_config(name: str) -> bool:
    """Remove a connector configuration by name."""
    configs = list_configs()
    survivors = [item for item in configs if item["name"] != name]
    if len(survivors) == len(configs):
        return False
    _write_configs([dict(item) for item in survivors])
    return True


def _connector_env(config: ConnectorConfig) -> dict[str, str]:
    """Build a minimal child environment plus explicitly inherited secrets."""
    base_names = {
        "PATH", "HOME", "USER", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL",
        "SystemRoot", "COMSPEC", "APPDATA", "LOCALAPPDATA", "USERPROFILE",
    }
    allowed = base_names.union(config["inherit_env"])
    return {key: value for key, value in os.environ.items() if key in allowed}


class StdioConnector:
    """Small synchronous JSON-RPC client for one external MCP server."""

    def __init__(self, config: ConnectorConfig, timeout: float = 10.0) -> None:
        self.config = config
        self._id = 0
        self._lock = threading.RLock()
        self._stderr: collections.deque[str] = collections.deque(maxlen=100)
        self.proc = subprocess.Popen(
            [config["command"], *config["args"]],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=_connector_env(config),
        )
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self._stdin = self.proc.stdin
        self._stdout = self.proc.stdout
        threading.Thread(target=self._drain_stderr, daemon=True).start()
        try:
            self._send(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "syscontrol-connectors", "version": "1.0"},
                },
                timeout=timeout,
            )
            self._notify("notifications/initialized")
        except Exception:
            self.close()
            raise

    def _drain_stderr(self) -> None:
        if self.proc.stderr is None:
            return
        with contextlib.suppress(OSError, ValueError):
            for line in iter(self.proc.stderr.readline, ""):
                self._stderr.append(line.rstrip())

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _readline(self, timeout: float) -> str:
        box: list[str] = []

        def read() -> None:
            with contextlib.suppress(OSError, ValueError):
                box.append(self._stdout.readline())

        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        thread.join(timeout)
        if thread.is_alive():
            raise TimeoutError(f"connector {self.config['name']} timed out")
        if not box or not box[0]:
            detail = "\n".join(self._stderr)
            raise RuntimeError(f"connector {self.config['name']} exited: {detail[-1000:]}")
        return box[0]

    def _send(self, method: str, params: dict | None = None, *, timeout: float = 30.0) -> dict:
        with self._lock:
            message: dict[str, Any] = {
                "jsonrpc": "2.0", "id": self._next_id(), "method": method,
            }
            if params is not None:
                message["params"] = params
            self._stdin.write(json.dumps(message) + "\n")
            self._stdin.flush()
            parsed = json.loads(self._readline(timeout))
        if not isinstance(parsed, dict):
            raise RuntimeError(f"connector {self.config['name']} returned a non-object response")
        if "error" in parsed:
            raise RuntimeError(str(parsed["error"]))
        return parsed

    def _notify(self, method: str) -> None:
        self._stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self._stdin.flush()

    def list_tools(self) -> list[dict[str, Any]]:
        response = self._send("tools/list", timeout=15.0)
        tools = response.get("result", {}).get("tools", [])
        return tools if isinstance(tools, list) else []

    def call_tool(self, name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        response = self._send(
            "tools/call", {"name": name, "arguments": arguments}, timeout=120.0,
        )
        content = response.get("result", {}).get("content", [])
        return content if isinstance(content, list) else []

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self._stdin.close()
        with contextlib.suppress(Exception):
            self.proc.terminate()
            self.proc.wait(timeout=2)
        if self.proc.poll() is None:
            with contextlib.suppress(Exception):
                self.proc.kill()


class ConnectorManager:
    """Own connector processes and namespaced tool routes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[str, StdioConnector] = {}
        self._routes: dict[str, tuple[str, str]] = {}
        self._errors: dict[str, str] = {}
        self._catalog: list[dict[str, Any]] = []

    def _client(self, config: ConnectorConfig) -> StdioConnector:
        client = self._clients.get(config["name"])
        if client is None:
            client = StdioConnector(config)
            self._clients[config["name"]] = client
        return client

    def tool_catalog(self) -> list[dict[str, Any]]:
        """Discover enabled connector tools and rebuild namespaced routes."""
        catalog: list[dict[str, Any]] = []
        routes: dict[str, tuple[str, str]] = {}
        with self._lock:
            if self._catalog:
                return [dict(tool) for tool in self._catalog]
            for config in list_configs():
                if not config["enabled"]:
                    continue
                try:
                    tools = self._client(config).list_tools()
                    self._errors.pop(config["name"], None)
                except Exception as exc:
                    self._errors[config["name"]] = str(exc)
                    continue
                for tool in tools:
                    original = str(tool.get("name", "")).strip()
                    if not original:
                        continue
                    namespaced = f"{config['name']}__{original}"
                    routes[namespaced] = (config["name"], original)
                    catalog.append({
                        "name": namespaced,
                        "description": f"[{config['name']}] {tool.get('description', '')}",
                        "inputSchema": tool.get("inputSchema", {"type": "object"}),
                        "parallel": False,
                        "annotations": tool.get("annotations", {}),
                        "_meta": {
                            **(tool.get("_meta", {}) if isinstance(tool.get("_meta"), dict) else {}),
                            "syscontrol": {"connector": config["name"], "external": True},
                        },
                    })
            self._routes = routes
            self._catalog = catalog
        return [dict(tool) for tool in catalog]

    def call_tool(self, namespaced_name: str, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        """Route a namespaced tool call to its connector."""
        with self._lock:
            route = self._routes.get(namespaced_name)
            if route is None:
                self.tool_catalog()
                route = self._routes.get(namespaced_name)
            if route is None:
                raise KeyError(namespaced_name)
            connector_name, original_name = route
            config = next(
                (item for item in list_configs() if item["name"] == connector_name), None,
            )
            if config is None:
                raise KeyError(namespaced_name)
            return self._client(config).call_tool(original_name, arguments)

    def status(self) -> list[dict[str, Any]]:
        """Return connector configuration and most recent connection state."""
        return [
            {
                **config,
                "connected": config["name"] in self._clients,
                "error": self._errors.get(config["name"]),
            }
            for config in list_configs()
        ]

    def refresh(self) -> None:
        """Close all processes and clear discovery state."""
        with self._lock:
            for client in self._clients.values():
                client.close()
            self._clients.clear()
            self._routes.clear()
            self._errors.clear()
            self._catalog.clear()
