"""Copying a project's auto-memory with a session (`--copy-memory`; DESIGN.md §8, §9).

Claude Code keeps auto-memory per project, in `projects/<slug>/memory/`, not per session, so the sessions
left behind may still read it: it is copied, never moved, and only what is missing at the destination is
added. A file there that differs refuses the whole move before anything changes, so nothing is overwritten
and nothing is merged by guesswork.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .. import portable
from ..caller import Refused
from ..claude_fs import ClaudeFS


def rel(slug: str, name: str = "") -> str:
    """A memory file's path under ~/.claude."""
    return str(Path("projects", slug, "memory", name)) if name else str(Path("projects", slug, "memory"))


def local(fs: ClaudeFS, slug: str) -> dict[str, str]:
    """The project's memory files here, by name within `memory/`, with their checksums; links are left out."""
    root = fs.projects / slug / "memory"
    if not root.is_dir():
        return {}
    return {
        str(f.relative_to(root)): portable.sha256(f)
        for f in sorted(root.rglob("*"))
        if f.is_file() and not f.is_symlink()
    }


def plan(src: dict[str, str], dest: dict[str, str | None]) -> list[str]:
    """The files to copy: those missing at the destination. Refuses if one there differs."""
    if clash := sorted(n for n, h in src.items() if dest.get(n) not in (None, h)):
        raise Refused(
            f"the project's memory differs at the destination in {', '.join(clash[:3])}"
            + (f" and {len(clash) - 3} more" if len(clash) > 3 else "")
            + "; settle those files first, or move without --copy-memory"
        )
    return sorted(n for n in src if dest.get(n) is None)


def copy_here(fs: ClaudeFS, src_slug: str, dest_slug: str, names: list[str]) -> None:
    """Copy memory files from one project to another on this machine, adding only, never overwriting."""
    for n in names:
        to = fs.projects / dest_slug / "memory" / n
        if to.exists():
            continue
        to.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fs.projects / src_slug / "memory" / n, to)
