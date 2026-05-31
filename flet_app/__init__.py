"""SysControl Flet GUI — the cross-platform desktop frontend.

This package is a pure-Python desktop GUI (built with Flet) that drives the
shared SysControl agent backend (``agent.core``) in-process.  It is the Windows
counterpart to the macOS SwiftUI app under ``swift/``; both speak to the same
MCP server and reuse the same ``~/.syscontrol/`` storage conventions.
"""
