"""Entry point for the SysControl Flet GUI (``syscontrol-gui``).

Also serves as the frozen-bundle dispatcher: when the packaged ``.exe`` is
re-exec'd by ``agent.core.MCPClient`` to act as the MCP server, this module
intercepts the ``--run-mcp-server`` sentinel and runs ``mcp.server.main()``
*before* importing Flet, so one bundled binary is both the GUI and the server.
"""

from __future__ import annotations

import importlib
import os
import sys

_SELFTEST_MODULES = ("ssl", "certifi", "openai", "psutil", "matplotlib")


def main() -> None:
    # Frozen child: run the MCP server (no window, no Flet import).
    if "--run-mcp-server" in sys.argv or os.environ.get("SYSCONTROL_MCP_CHILD") == "1":
        from mcp.server import main as server_main
        server_main()
        return

    # CI smoke check that the frozen bundle can import its heavy deps + TLS.
    # Success is signalled by exit code 0 (a windowed build has no stdout, so
    # the print is best-effort only).
    if "--selftest" in sys.argv:
        for mod in _SELFTEST_MODULES:
            importlib.import_module(mod)
        if sys.stdout is not None:
            print("selftest ok")
        return

    import flet as ft

    from flet_app.app import build_app
    ft.run(build_app)


if __name__ == "__main__":
    main()
