"""
SysControl CLI self-updater.

Resolves the current installed version, queries GitHub for the latest
release, and (when available) shells out to ``uv tool install --force`` to
upgrade in place.  Used by the ``/update`` slash command and the
``syscontrol --update`` flag.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from importlib import metadata

REPO_URL = "https://github.com/ks6573/SysControl.git"
LATEST_RELEASE_URL = "https://api.github.com/repos/ks6573/SysControl/releases/latest"
_REQUEST_TIMEOUT = 8.0


@dataclass(frozen=True)
class UpdateInfo:
    current: str
    latest: str | None
    is_newer: bool
    tag_name: str | None = None
    html_url: str | None = None
    error: str | None = None


def current_version() -> str:
    """Return the installed package version, or 'unknown' if not packaged."""
    try:
        return metadata.version("syscontrol")
    except metadata.PackageNotFoundError:
        return "unknown"


def _parse_semver(s: str) -> tuple[int, ...]:
    parts = s.lstrip("vV").split("-")[0].split(".")
    out: list[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            return ()
    return tuple(out)


def check_for_update() -> UpdateInfo:
    """Compare the installed version to the latest GitHub release."""
    current = current_version()
    try:
        req = urllib.request.Request(
            LATEST_RELEASE_URL,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "syscontrol-cli"},
        )
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return UpdateInfo(current=current, latest=None, is_newer=False, error=str(exc))

    tag = str(payload.get("tag_name") or "")
    latest_clean = tag.lstrip("vV")
    cur_t = _parse_semver(current)
    lat_t = _parse_semver(latest_clean)
    is_newer = bool(cur_t and lat_t and lat_t > cur_t)
    return UpdateInfo(
        current=current,
        latest=latest_clean or None,
        is_newer=is_newer,
        tag_name=tag or None,
        html_url=payload.get("html_url"),
    )


def update_via_uv() -> tuple[bool, str]:
    """Run ``uv tool install --force`` to reinstall syscontrol from master.

    Returns a ``(ok, message)`` tuple.  ``ok=False`` when uv is missing
    or the subprocess exits non-zero.
    """
    if shutil.which("uv") is None:
        return False, (
            "uv is not on PATH. Reinstall the CLI with:\n"
            '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/'
            'ks6573/SysControl/master/install-cli.sh)"'
        )
    cmd = ["uv", "tool", "install", "--force", f"git+{REPO_URL}"]
    try:
        result = subprocess.run(cmd, check=False, capture_output=True, text=True, timeout=600)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"uv tool install failed: {exc}"
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "uv tool install exited non-zero").strip()
    return True, (result.stdout.strip() or "Updated successfully.")
