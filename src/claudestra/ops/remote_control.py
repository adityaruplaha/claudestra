"""Remote Control for every session, which claudestra requires (DESIGN.md §7.1).

Claude Code reads `remoteControlAtStartup` as tested against 2.1.300: `false` in a folder's own settings
(`.claude/settings.json` or `settings.local.json`) turns it off there, whatever else says; otherwise the first
of managed settings, the user's settings and the older copy in `~/.claude.json` that sets it decides; a
folder's settings cannot turn it on. `claudestra install remote-control` sets it in the user's settings.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..caller import Refused
from ..claude_fs import ClaudeFS
from ..portable import atomic_write_text, read_json
from . import guard

KEY = "remoteControlAtStartup"


def _value(path: Path) -> bool | None:
    data = read_json(path) if path.is_file() else None
    v = data.get(KEY) if isinstance(data, dict) else None
    return v if isinstance(v, bool) else None


def managed_files() -> list[Path]:
    return [guard.MANAGED / "managed-settings.json", *sorted(guard.MANAGED.glob("managed-settings.d/*.json"))]


def effective(fs: ClaudeFS) -> tuple[bool | None, str]:
    """What sets it for a folder with no setting of its own, and where that comes from."""
    managed = [(v, str(p)) for p in managed_files() if (v := _value(p)) is not None]
    if managed:
        return managed[-1][0], f"managed settings ({managed[-1][1]})"
    for path, label in ((guard.settings_path(fs), "the user's settings"), (fs.config, "~/.claude.json")):
        if (v := _value(path)) is not None:
            return v, f"{label} ({path})"
    return None, "nothing sets it"


def off_in(fs: ClaudeFS, folder: Path) -> list[Path]:
    """The settings files in `folder` that turn it off there."""
    user = guard.settings_path(fs).resolve()
    files = [folder / ".claude" / "settings.json", folder / ".claude" / "settings.local.json"]
    return [p for p in files if p.resolve() != user and _value(p) is False]


def problems(fs: ClaudeFS, folders: list[Path]) -> list[str]:
    """Why some session here would start without Remote Control: none if every one starts with it."""
    out = []
    value, source = effective(fs)
    if value is False:
        out.append(f"{source} turns it off")
    elif value is None:
        out.append("nothing turns it on, so it is left to Claude Code's default")
    out += [f"{p} turns it off in {folder}" for folder in folders for p in off_in(fs, folder)]
    return out


def enable(fs: ClaudeFS, dry: bool) -> list[str]:
    """Turn it on in the user's settings, keeping the rest; what it did, or would do."""
    path = guard.settings_path(fs)
    for p in managed_files():
        if _value(p) is False:
            raise Refused(f"managed settings turn Remote Control off ({p}); only whoever manages them can change that")
    data = read_json(path) if path.is_file() else {}
    if not isinstance(data, dict):
        raise Refused(f"cannot read {path} as a JSON object")
    if data.get(KEY) is True:
        return [f"Remote Control is on for every session in {path}"]
    out = [f"{'would set' if dry else 'set'} {KEY}: true in {path}"]
    if not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps({**data, KEY: True}, indent=2) + "\n")
    return out
