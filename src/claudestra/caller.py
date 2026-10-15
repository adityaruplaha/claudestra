"""Who is calling claudestra, and what it may do (DESIGN.md §6.1, §6.4).

A guard against a session acting by mistake, not security: every session runs as the same user.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .claude_fs import ClaudeFS, PidFile
from .proctree import claude_chain
from .runners import UNIT
from .trust import Trust


class Refused(Exception):
    """An action this caller may not take, or that would be unsafe."""


def login_invocation() -> str | None:
    """The current invocation ID of claudestra's login unit, or None if it has none."""
    try:
        r = subprocess.run(
            ["systemctl", "--user", "show", UNIT, "-p", "InvocationID", "--value"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    v = r.stdout.strip()
    return v if r.returncode == 0 and v else None


def in_login_unit(proc: Path = Path("/proc")) -> bool:
    """Whether this process runs in the login unit's own cgroup. An INVOCATION_ID can be set by
    anyone starting a process (`systemd-run -E`); the cgroup a unit's processes run in cannot."""
    try:
        lines = (proc / "self" / "cgroup").read_text().splitlines()
    except OSError:
        return False
    return any(line.rstrip().endswith(f"/{UNIT}") for line in lines)


@dataclass
class Caller:
    kind: str  # "human", "device", "folder", "unscoped" (a session with no scope), or "login" (claudestra's login unit)
    session: str | None = None
    name: str | None = None
    pid: int | None = None
    folder: Path | None = None  # a folder-scope caller's validated folder
    note: str = ""  # why a folder-scope caller has no folder

    def describe(self) -> str:
        if self.kind == "human":
            return "the user, at a terminal"
        if self.kind == "login":
            return f"claudestra's login unit ({UNIT})"
        if self.kind == "unscoped":
            return f"session {self.name!r} ({self.session}, pid {self.pid}, no scope)"
        return f"{self.kind}-scope {self.name!r} ({self.session}, pid {self.pid})"


def filed_under(fs: ClaudeFS, sid: str) -> list[str]:
    """The slugs holding the session's transcript on this machine."""
    return [p.parent.name for p in fs.projects.glob(f"*/{sid}.jsonl")]


def transcript_problem(fs: ClaudeFS, host: str, sid: str, folder: Path | None) -> str | None:
    """Why `folder` is not where the session is filed, if it is not: for a staffer, the folder its staff
    file gives.

    It must be the folder its session is filed under, redirects followed, since resuming from any
    other folder forks the session (DESIGN.md §6.2); and, where the transcript records the folder
    the session started in, that very folder, since different folders can share a slug.
    """
    found = filed_under(fs, sid)
    if not found:
        return f"session {sid} has no transcript on {host}"
    if len(found) > 1:
        return f"session {sid} is filed under {len(found)} slugs on {host}: {', '.join(found)}"
    if not folder or fs.filed_slug(folder) != found[0]:
        return f"session {sid} is filed under {found[0]} on {host}, not under {folder}; its staff file is out of date"
    first = fs.first_cwd(fs.transcript(found[0], sid))
    if first and fs.filed_slug(first) == found[0] and Path(os.path.normpath(first)) != folder:
        return f"session {sid} started in {first}, which shares a slug with {folder}; its staff file names the wrong folder"
    return None


def validated_folder(fs: ClaudeFS, host: str, trust: Trust, pf: PidFile) -> tuple[Path | None, str]:
    """A folder-scope session's folder: its staff file's, if the slug and its process agree."""
    me = trust.staff_file(pf.session_id)
    if me is None or me.folder is None:
        return None, f"no staff file gives its folder on {host}"
    if why := transcript_problem(fs, host, me.session, me.folder):
        return None, why
    # The slug maps several folders to one name, so the folder must also be the one Claude Code
    # recorded the process as running in.
    cwd = pf.get("cwd")
    if not isinstance(cwd, str) or Path(os.path.normpath(cwd)) != me.folder:
        return None, f"its staff file names {me.folder}, but the session runs in {cwd}"
    return me.folder, ""


def identify(
    fs: ClaudeFS,
    host: str,
    trust: Trust,
    start_pid: int | None = None,
    claude_env: bool | None = None,
    tty: bool | None = None,
) -> Caller:
    """The caller, from the Claude processes in its process chain (proctree.py).

    The nearest Claude process is the caller, and its session must be one Claude Code registered for
    it; a Claude process with no session file (a headless or child run, or an unknown format) is
    refused rather than guessed at. With no Claude process in the chain, the caller is the user only at
    a terminal and without a Claude session's environment.
    """
    procs = claude_chain(fs, start_pid)
    if procs:
        nearest = procs[0]
        pf = nearest.pid_file
        if pf is None or not pf.session_id:
            raise Refused(
                f"called from a Claude process (pid {nearest.proc.pid}, {nearest.proc.exe or nearest.proc.comm}) with no session file; claudestra cannot tell which session it is"
            )
        sid = pf.session_id
        kind = trust.scope(sid) or "unscoped"
        name = pf.get("name")
        caller = Caller(kind, sid, name if isinstance(name, str) else None, pf.pid)
        if kind == "folder":
            caller.folder, caller.note = validated_folder(fs, host, trust, pf)
        return caller
    if claude_env is None:
        claude_env = any(k.startswith("CLAUDE") for k in os.environ)
    if claude_env:
        raise Refused("called with a Claude session's environment but no Claude process above it in the process tree")
    # claudestra's login unit: only the current invocation of that very unit, which may only start this
    # machine's managers.
    inv = os.environ.get("INVOCATION_ID")
    if inv and in_login_unit(fs.proc) and inv == login_invocation():
        return Caller("login")
    if not (sys.stdin.isatty() if tty is None else tty):
        raise Refused("not called from a terminal or from a known Claude session")
    return Caller("human")
