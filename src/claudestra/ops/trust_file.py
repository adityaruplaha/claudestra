"""Writing trust.yaml, for `claudestra trust` (DESIGN.md §6.1).

The file is claudestra's to write, in its own layout: machines first, then sessions, each session ID
followed by a comment with the session's current name. The comments are generated on every write, so
they never go stale, and a comment written by hand does not survive the next change.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import yaml

from ..caller import Refused
from ..portable import atomic_write_text

HEADER = (
    "# Written by `claudestra trust`; change it with that command. The comment after each session ID\n"
    "# is that session's name, regenerated on every change.\n"
)


def read(path: Path) -> dict:
    """trust.yaml as plain data, with both sections present."""
    raw = (yaml.safe_load(path.read_text()) or {}) if path.is_file() else {}
    if not isinstance(raw, dict):
        raise Refused(f"{path} is not a mapping; fix it by hand first")
    raw["machines"] = raw.get("machines") or {}
    raw["sessions"] = raw.get("sessions") or {}
    return raw


def _q(v: object) -> str:
    """A scalar as YAML writes it, quoted only where it has to be."""
    s = yaml.safe_dump(v, default_flow_style=True, allow_unicode=True, width=10_000).strip()
    return s[:-4].rstrip() if s.endswith("\n...") else s.removesuffix("...").rstrip()


def _comment(sid: str, name_of: Callable[[str], str | None]) -> str:
    """ " # <its name>", or nothing where the session has no name."""
    name = (name_of(sid) or "").replace("\n", " ").strip()
    return f" # {name}" if name else ""


def emit(raw: dict, name_of: Callable[[str], str | None]) -> str:
    out = [HEADER]
    if raw["machines"]:
        out.append("machines:")
        for host, mc in raw["machines"].items():
            out.append(f"  {_q(str(host))}:")
            out.append(f"    home: {_q(mc['home'])}")
            out.append(f"    machine_id: {_q(mc['machine_id'])}")
            if mc.get("ssh"):
                out.append(f"    ssh: {_q(mc['ssh'])}")
            if mc.get("autostart"):
                out.append("    autostart:")
                out += [f"      - {sid}{_comment(sid, name_of)}" for sid in mc["autostart"]]
            if mc.get("protected"):
                out.append("    protected:")
                out += [f"      - {_q(f)}" for f in mc["protected"]]
        out.append("")
    if raw["sessions"]:
        out.append("sessions:")
        for sid, entry in raw["sessions"].items():
            out.append(f"  {sid}:{_comment(sid, name_of)}")
            out.append(f"    scope: {_q(entry['scope'])}")
    return "\n".join(out).rstrip() + "\n"


def _tidy(raw: dict) -> None:
    """Drop the empty parts the layout leaves out, so what is written reads back the same."""
    for mc in raw["machines"].values():
        for k in ("ssh", "autostart", "protected"):
            if not mc.get(k):
                mc.pop(k, None)


def change(path: Path, edit: Callable[[dict], None], name_of: Callable[[str], str | None]) -> str | None:
    """Apply `edit` to trust.yaml and write it back; returns the text before, for an undo (None if it
    did not exist). What is written must load again as it was emitted."""
    before = path.read_text() if path.is_file() else None
    raw = read(path)
    edit(raw)
    _tidy(raw)
    text = emit(raw, name_of)
    if yaml.safe_load(text) != {k: v for k, v in raw.items() if v}:
        raise Refused("claudestra would write a trust.yaml that does not read back as intended; nothing changed")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, text)
    return before


def restore(path: Path, before: str | None) -> None:
    """Put trust.yaml back as it was before a change."""
    if before is None:
        path.unlink()
    else:
        atomic_write_text(path, before)
