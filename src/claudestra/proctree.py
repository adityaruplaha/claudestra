"""The caller's process chain, the Claude Code processes in it, and the sessions they host.

Who is calling claudestra is decided from this chain, never from the environment, which any process can
set (DESIGN.md §6.4). A Claude process is recognised by its executable or command name being
`claude` (the CLI, or the native binary inside VS Code's extension), and mapped to its session
through ~/.claude/sessions/<pid>.json when that file's procStart matches the process.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .claude_fs import ClaudeFS, PidFile


@dataclass
class Proc:
    pid: int
    ppid: int
    start: str
    comm: str
    exe: str | None

    @property
    def is_claude(self) -> bool:
        return self.comm == "claude" or (self.exe is not None and os.path.basename(self.exe) == "claude")


@dataclass
class ClaudeProc:
    """A Claude process in the chain that called claudestra."""

    proc: Proc
    pid_file: PidFile | None  # None: a Claude process with no matching session file
    depth: int = 0  # its place in the chain: 1 is claudestra's parent, 2 that one's parent, and so on

    @property
    def session_id(self) -> str | None:
        return self.pid_file.session_id if self.pid_file else None

    @property
    def session_name(self) -> str | None:
        n = self.pid_file.get("name") if self.pid_file else None
        return n if isinstance(n, str) else None

    def describe(self) -> str:
        what = self.proc.exe or self.proc.comm
        who = (
            f"session {self.session_id}" + (f" ({self.session_name})" if self.session_name else "")
            if self.session_id
            else "no session file"
        )
        return f"depth {self.depth}: pid {self.proc.pid}, {what}, {who}"


def read_proc(fs: ClaudeFS, pid: int) -> Proc | None:
    st = fs.proc_stat(pid)
    if st is None:
        return None
    base = fs.proc / str(pid)
    try:
        comm = (base / "comm").read_text().strip()
    except OSError:
        comm = ""
    try:
        exe: str | None = os.readlink(base / "exe")
    except OSError:
        exe = None
    return Proc(pid, st.ppid, st.start, comm, exe)


def chain(fs: ClaudeFS, start_pid: int | None = None) -> list[Proc]:
    """The process `start_pid` (default: this process's parent) and every ancestor up to init."""
    out, pid, seen = [], start_pid if start_pid is not None else os.getppid(), set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        p = read_proc(fs, pid)
        if p is None:
            break
        out.append(p)
        pid = p.ppid
    return out


def claude_chain(fs: ClaudeFS, start_pid: int | None = None) -> list[ClaudeProc]:
    """The Claude processes in the chain, nearest first, each with its session if one matches.

    A process counts when it looks like Claude or when a live session file names it, so a renamed
    binary that Claude Code itself registered is still found.
    """
    out = []
    for depth, p in enumerate(chain(fs, start_pid), start=1):
        pf = fs.live_pid_file(p.pid)
        if pf is not None or p.is_claude:
            out.append(ClaudeProc(p, pf, depth))
    return out


def describe(fs: ClaudeFS, start_pid: int | None = None) -> list[str]:
    """One line per process in the chain, for `claudestra whoami --chain`."""
    lines = []
    for p in chain(fs, start_pid):
        pf = fs.live_pid_file(p.pid)
        tag = f"  session {pf.session_id}" if pf else ("  claude, no session file" if p.is_claude else "")
        lines.append(f"{p.pid:>8}  {p.comm:<12} {p.exe or '-'}{tag}")
    return lines
