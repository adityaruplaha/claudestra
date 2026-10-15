"""What every mutating operation shares: the lock, the log, the path guard, a session's stores, the
refusals, and a journal that undoes a half-finished operation.

Every mutating command takes the lock, refuses rather than guesses, has a dry run, and logs what it
did (DESIGN.md §5). claudestra's own state is its log, its lock and the backups of what it rewrites.
"""

from __future__ import annotations

import contextlib
import fcntl
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from .. import portable
from ..caller import Caller, Refused
from ..claude_fs import ClaudeFS
from ..model import SessionRecord

STATE_DIR = portable.state_dir(Path.home())
LIVE_JOB_STATES = ("running", "working", "blocked")


@contextlib.contextmanager
def locked() -> Iterator[None]:
    """claudestra's lock, without waiting: a second claudestra that wants to change something is refused."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_DIR / "lock", "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused(
                "another claudestra is changing something on this machine; try again when it has finished"
            ) from None
        yield


def log(caller: Caller, action: str, subject: str, detail: str = "") -> None:
    portable.log_line(
        STATE_DIR,
        {
            "at": portable.now_local(),
            "caller": caller.describe(),
            "action": action,
            "subject": subject,
            "detail": detail,
        },
    )


def backup_dir(what: str, session_id: str) -> Path:
    """Where an operation keeps copies of the files it rewrites, outside the trash."""
    return STATE_DIR / "backups" / f"{portable.stamp()}-{what}-{session_id}"


def guard(fs: ClaudeFS, p: Path) -> None:
    """A path claudestra may move: inside ~/.claude, and never a project's auto-memory."""
    root = fs.root.resolve()
    rp = p.parent.resolve() / p.name  # the entry itself, not what a symlink there points to
    if not rp.is_relative_to(root) or "memory" in rp.relative_to(root).parts:
        raise Refused(f"refusing {rp}: outside ~/.claude, or inside a memory folder")


@dataclass
class Stores:
    """Everything on this machine that belongs to one session, each with a label unique within it."""

    session_id: str
    items: list[tuple[str, Path]] = field(default_factory=list)  # (label, path)

    def paths(self) -> list[Path]:
        return [p for _, p in self.items]


def stores(fs: ClaudeFS, s: SessionRecord, secondary_ids: frozenset[str] | set[str] = frozenset()) -> Stores:
    """The transcript(s), every <id>/ folder (a split session has one under another slug), the set-aside
    copies, and the entries in the keyed stores under the session's ID or a secondary one.

    The background job's folder is left out: it belongs to Claude Code's supervisor (DESIGN.md §8).
    """
    out = Stores(s.session_id)
    sid = s.session_id
    for slug_name in sorted({*s.homes, *(p.parent.name for p in fs.projects.glob(f"*/{sid}"))}):
        if (t := fs.transcript(slug_name, sid)).is_file():
            out.items.append((f"projects/{slug_name}/{t.name}", t))
        if (d := fs.projects / slug_name / sid).is_dir():
            out.items.append((f"projects/{slug_name}/{sid}", d))
    out.items += [(f"projects/{slug_name}/{f.name}", f) for slug_name, f, other in fs.set_aside() if other == sid]
    out.items += fs.keyed_entries(sid, secondary_ids)
    return out


def size(p: Path) -> int:
    """Bytes on disk, counting a symlink as itself and never following one."""
    if p.is_symlink() or p.is_file():
        return p.lstat().st_size
    return sum(f.lstat().st_size for f in p.rglob("*") if f.is_symlink() or f.is_file())


def refuse_link_conflicts(fs: ClaudeFS, paths: list[Path]) -> None:
    """Refuse to move `paths` when that would break or split a symlink: a link inside them, or a link
    elsewhere pointing into them. Two sessions then share the file, and the user settles which owns it."""
    found = []
    roots = [p.parent.resolve() / p.name for p in paths]
    for link, target, dangling in fs.links():
        if any(link == r or link.is_relative_to(r) for r in roots):
            found.append(f"{link} is a symlink (to {target}{', which is missing' if dangling else ''})")
        elif not dangling and any((real := link.resolve()) == r or real.is_relative_to(r) for r in roots):
            found.append(f"{real} is the target of the symlink {link}")
    if found:
        raise Refused(
            "; ".join(found[:3])
            + ("; and more" if len(found) > 3 else "")
            + ". Settle which session owns the file first"
        )


def refuse_if_running(fs: ClaudeFS, s: SessionRecord) -> None:
    """Refuse a session that runs, read from the disk now rather than from a model built earlier."""
    if pid := portable.running_pid(fs.sessions, fs.proc, s.session_id):
        raise Refused(f"{s.session_id} is running (pid {pid}); stop it first")
    if any(j.state in LIVE_JOB_STATES for j in s.jobs):
        raise Refused(f"{s.session_id} has a live background job; stop it with claude agents first")


def move_path(src: Path, dst: Path) -> None:
    try:
        portable.move_into(src, dst)
    except FileExistsError as e:
        raise Refused(str(e)) from None


class Journal:
    """The moves an operation has made, so a failure part way puts every one of them back."""

    def __init__(self) -> None:
        self.done: list[tuple[Path, Path]] = []

    def move(self, src: Path, dst: Path) -> None:
        move_path(src, dst)
        self.done.append((src, dst))

    def undo(self) -> list[str]:
        """Move everything back, newest first; what could not go back is returned, not raised."""
        stuck = []
        for src, dst in reversed(self.done):
            try:
                portable.move_into(dst, src)
            except OSError as e:
                stuck.append(f"{dst} -> {src}: {e}")
        self.done.clear()
        return stuck


def remove_tree(root: Path) -> None:
    """Delete a folder that is known to hold only files and folders: unlink files, then rmdir bottom-up,
    so anything unexpected makes it fail rather than be destroyed."""
    for f in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if f.is_symlink() or f.is_file():
            f.unlink()
        elif f.is_dir():
            f.rmdir()
    root.rmdir()
