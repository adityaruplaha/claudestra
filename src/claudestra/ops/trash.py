"""`claudestra trash`, `restore`, `purge`: remove sessions to a trash and back.

Who may run each is DESIGN.md §6.1; why a trash refuses what it refuses is DESIGN.md §9. The trash's
layout is portable.py's (TRASH, MANIFEST, trash_into), shared with the other machine. Nothing is deleted
except by purge.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .. import portable
from ..caller import Caller, Refused
from ..claude_fs import ClaudeFS
from ..model import SessionRecord
from ..trust import Trust
from .common import (
    guard,
    log,
    move_path,
    refuse_if_running,
    refuse_link_conflicts,
    remove_tree,
    size,
    stores,
)


def trash_dir(fs: ClaudeFS) -> Path:
    return fs.root / portable.TRASH


@dataclass
class Plan:
    session: SessionRecord
    items: list[tuple[str, Path]]  # (label, path)
    bytes: int


def plan(fs: ClaudeFS, trust: Trust, s: SessionRecord, recent_minutes: float) -> Plan:
    """What trashing the session takes, refusing what cannot be done. Who may is the action's to decide."""
    refuse_if_running(fs, s)
    if trust.is_protected(s.folder, s.homes[0]):
        raise Refused(f"{s.session_id} is filed in a protected folder; trash it by hand if the user says so")
    # A crash leaves no pid file, so a session written very recently may still be open somewhere.
    if (age := (time.time() - s.mtime) / 60) < recent_minutes:
        raise Refused(
            f"{s.session_id} was written {age:.0f} min ago; wait, or pass --recent-minutes 0 if the user is sure it is closed"
        )
    st = stores(fs, s, fs.read_meta(fs.transcript(s.homes[0], s.session_id), s.session_id).secondary_ids)
    refuse_link_conflicts(fs, st.paths())
    for p in st.paths():
        guard(fs, p)
    return Plan(s, st.items, sum(size(p) for p in st.paths()))


def apply(fs: ClaudeFS, caller: Caller, plan: Plan, reason: str | None = None) -> Path:
    refuse_if_running(fs, plan.session)  # again: the user may have resumed it while the plan was shown
    try:
        entry = portable.trash_into(
            fs.root, plan.session.session_id, plan.items, plan.session.homes[0], plan.session.name, reason
        )
    except FileExistsError as e:
        raise Refused(str(e)) from None
    log(caller, "trash", plan.session.session_id, entry.name)
    return entry


def entries(fs: ClaudeFS) -> list[tuple[Path, dict | None]]:
    d = trash_dir(fs)
    return [(e, portable.read_manifest(e)) for e in sorted(d.iterdir()) if e.is_dir()] if d.is_dir() else []


def find_entry(fs: ClaudeFS, token: str) -> tuple[Path, dict]:
    if len(token) < 8:
        raise Refused("give a trash entry's name, or 8 or more characters of its session ID")
    hits = [
        (e, mf)
        for e, mf in entries(fs)
        if mf and (e.name == token or e.name.endswith(token) or str(mf.get("session_id", "")).startswith(token))
    ]
    if not hits:
        raise Refused(f"no trash entry with a manifest matches {token!r}")
    if len(hits) > 1:
        raise Refused(f"{token!r} matches {len(hits)} entries: {', '.join(e.name for e, _ in hits)}")
    return hits[0]


def restore(fs: ClaudeFS, caller: Caller, token: str, dry: bool) -> list[str]:
    """Move an entry's stores back. The manifest is updated after each move, so a restore that fails
    part way can be run again, and what is already back is skipped."""
    entry, mf = find_entry(fs, token)
    sid = str(mf.get("session_id"))
    pending = [mv for mv in mf.get("moves", []) if not (Path(mv["from"]).exists() and not Path(mv["to"]).exists())]
    back = [Path(mv["from"]) for mv in mf.get("moves", []) if mv not in pending]
    if elsewhere := [p for p in fs.projects.glob(f"*/{sid}.jsonl") if p not in back]:
        raise Refused(f"{sid} has a transcript again at {elsewhere[0]}; restoring would give it two homes")
    for mv in pending:
        src, dst = Path(mv["to"]), Path(mv["from"])
        if not (src.exists() or src.is_symlink()):
            raise Refused(f"missing from the trash: {src}")
        if dst.exists() or dst.is_symlink():
            raise Refused(f"{dst} already exists; refusing to overwrite it")
        guard(fs, dst)
    if dry:
        return [f"would restore {mv['from']}" for mv in pending]
    for mv in list(pending):
        move_path(Path(mv["to"]), Path(mv["from"]))
        mf["moves"] = [m for m in mf["moves"] if m is not mv]
        portable.write_manifest(entry, mf)
    (entry / portable.MANIFEST).unlink()
    for d in sorted((p for p in entry.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        d.rmdir()  # only the emptied scaffolding; anything left makes this fail
    entry.rmdir()
    log(caller, "restore", sid, entry.name)
    return [f"restored {mv['from']}" for mv in pending]


def purgeable(fs: ClaudeFS, older_than_days: float) -> list[Path]:
    if older_than_days < 1:
        raise Refused("--older-than must be at least 1 day")
    cutoff = time.time() - older_than_days * 86400
    return [e for e, _ in entries(fs) if e.stat().st_mtime < cutoff]


def purge(fs: ClaudeFS, caller: Caller, doomed: list[Path]) -> list[str]:
    """Delete exactly the entries given, as `purgeable` listed them and the user was shown."""
    root = trash_dir(fs).resolve()
    out = []
    for e in doomed:
        if e.resolve().parent != root:
            raise Refused(f"refusing {e}: not directly inside the trash")
        out.append(f"deleted {e.name} ({size(e) / 1e6:.2f} MB)")
        remove_tree(e)
        log(caller, "purge", e.name)
    return out
