"""Extract and validate inline chart-image paths from MCP tool results.

Ported from ``agent/bridge.py`` (the macOS app's path).  Chart/screenshot MCP
tools append ``[chart_image:/abs/path]`` markers to their text result, with the
PNG saved under the system temp dir.  We surface only paths that are inside the
temp dir AND carry the expected prefix, so a tool result cannot coax the GUI
into loading an arbitrary file off disk.
"""

from __future__ import annotations

import os
import re
import tempfile

_CHART_IMAGE_RE = re.compile(r"\[chart_image:(.+?)\]")
_INLINE_IMAGE_PREFIXES = ("syscontrol_chart_", "syscontrol_artifact_")
_TMP_DIR_REAL = os.path.realpath(tempfile.gettempdir())


def extract_chart_paths(result: str) -> list[str]:
    """Return validated, existing inline chart-image absolute paths in *result*."""
    paths: list[str] = []
    for match in _CHART_IMAGE_RE.finditer(result or ""):
        resolved = os.path.realpath(match.group(1))
        try:
            # commonpath raises ValueError across drives on Windows — treat as
            # "not under the temp dir" rather than crashing.
            in_tmp = os.path.commonpath([resolved, _TMP_DIR_REAL]) == _TMP_DIR_REAL
        except ValueError:
            in_tmp = False
        if not in_tmp:
            continue
        if not os.path.basename(resolved).startswith(_INLINE_IMAGE_PREFIXES):
            continue
        if os.path.exists(resolved) and resolved not in paths:
            paths.append(resolved)
    return paths


def strip_chart_markers(text: str) -> str:
    """Remove ``[chart_image:...]`` markers from text shown to the user."""
    return _CHART_IMAGE_RE.sub("", text or "").strip()
