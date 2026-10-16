"""Hiring and dismissing, on the files: staff.d/<id>.yaml written by claudestra, and moved to
staff-dismissed.d/ and back. Who may is the actions' to decide (actions/hire.py, actions/dismiss.py)."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..caller import Refused
from ..portable import atomic_write_text
from ..trust import DISMISSED, STAFF, STAFF_HEADER


def staff_path(config: Path, sid: str) -> Path:
    return config / STAFF / f"{sid}.yaml"


def dismissed_path(config: Path, sid: str) -> Path:
    return config / DISMISSED / f"{sid}.yaml"


def dismissed(config: Path, sid: str) -> dict | None:
    """A dismissed staffer's staff file as it was, or None if it was never dismissed."""
    p = dismissed_path(config, sid)
    if not p.is_file():
        return None
    raw = yaml.safe_load(p.read_text()) or {}
    if not isinstance(raw, dict):
        raise Refused(f"{p} is not a mapping; fix it by hand first")
    return raw


def emit(name: str, folders: dict[str, str], description: str) -> str:
    """A staff file in claudestra's layout: the header, then name, folder per machine, description."""
    body = yaml.safe_dump(
        {"name": name, "folder": dict(folders), "description": description},
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )
    return STAFF_HEADER + body


def hire(config: Path, sid: str, name: str, folders: dict[str, str], description: str) -> None:
    """Write the staff file; a dismissed one for the same session is removed, since it is now this."""
    p = staff_path(config, sid)
    if p.exists():
        raise Refused(f"{p} exists already")
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, emit(name, folders, description))
    if (d := dismissed_path(config, sid)).exists():
        d.unlink()


def unhire(config: Path, sid: str, was_dismissed: str | None) -> None:
    """Undo a hire: remove the staff file, and put back the dismissed one it replaced."""
    if was_dismissed is not None:
        d = dismissed_path(config, sid)
        d.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(d, was_dismissed)
    staff_path(config, sid).unlink()


def dismiss(config: Path, sid: str) -> str | None:
    """Move the staff file to staff-dismissed.d/, exactly as it is, over any older dismissed copy, whose text
    it returns for an undo. The staff file is the newer: hiring removes the dismissed copy it came from."""
    src, dst = staff_path(config, sid), dismissed_path(config, sid)
    older = dst.read_text() if dst.exists() else None
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dst)
    return older


def undismiss(config: Path, sid: str, older: str | None = None) -> None:
    """Undo a dismissal: move the file back, exactly as it was, and put back any older dismissed copy."""
    dismissed_path(config, sid).rename(staff_path(config, sid))
    if older is not None:
        atomic_write_text(dismissed_path(config, sid), older)
