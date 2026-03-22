#!/bin/bash
# Double-click this file in Finder to launch SysControl GUI from source.
# No rebuild needed — picks up code changes instantly.

cd "$(dirname "$0")"
exec uv run python gui.py
