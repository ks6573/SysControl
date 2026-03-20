#!/usr/bin/env python3
"""SysControl GUI — entry-point shim."""

try:
    from agent.gui.app import main
except ImportError as exc:
    import sys
    print(
        "PySide6 is required for the GUI. Install with:\n"
        "  uv pip install -e '.[gui]'\n"
        f"\nImport error: {exc}",
        file=sys.stderr,
    )
    sys.exit(1)

if __name__ == "__main__":
    main()
