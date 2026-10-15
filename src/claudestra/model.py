"""The model (DESIGN.md §4): sessions, their runs and homes, and the staffers that name them.

Computed from the disk on each command, with nothing stored of its own: Claude Code owns those
files and changes them underneath any copy.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path

from .claude_fs import UUID, ClaudeFS, PidFile, bridge_suffix, names
from .portable import machine_id, slug
from .trust import StaffFile, Trust


@dataclass
class Machine:
    hostname: str
    machine_id: str | None  # claudestra's derived ID, never the raw /etc/machine-id
    home: Path

    @classmethod
    def here(cls, home: Path | None = None) -> Machine:
        return cls(socket.gethostname(), machine_id(), home or Path.home())


@dataclass
class Run:
    """A live process hosting a session."""

    pid: int
    proc_start: str
    session_id: str
    kind: str  # interactive, background, ...
    status: str | None
    cwd: str | None
    name: str | None
    bridge_id: str | None


@dataclass
class Job:
    """A background job Claude Code's supervisor knows, running or not."""

    short: str
    session_id: str | None
    state: str | None
    cwd: str | None
    folder: Path  # the job's folder under ~/.claude/jobs/


@dataclass
class SessionRecord:
    session_id: str
    homes: list[str]  # slugs holding its transcript; one, unless something is wrong
    folder: Path | None = None  # the folder its home slug stands for, where known
    names: list[str] = field(default_factory=list)  # latest first
    bridge_ids: set[str] = field(default_factory=set)
    aliases: set[str] = field(default_factory=set)
    runs: list[Run] = field(default_factory=list)
    jobs: list[Job] = field(default_factory=list)
    staff_file: StaffFile | None = None
    first_cwd: str | None = None
    size: int = 0
    mtime: float = 0.0

    @property
    def name(self) -> str | None:
        return self.names[0] if self.names else None

    @property
    def state(self) -> str:
        """Running (each run's kind, status and pid), or stopped, with its job's state if it has one."""
        if self.runs:
            return ", ".join(f"{r.kind} {r.status or ''}".strip() + f" (pid {r.pid})" for r in self.runs)
        jobs = [j for j in self.jobs if j.state]
        return f"stopped (job {jobs[0].state})" if jobs else "stopped"


@dataclass
class Model:
    machine: Machine
    sessions: dict[str, SessionRecord]
    runs: list[Run]
    stale_pid_files: list[PidFile]
    jobs: list[Job]
    folders_by_slug: dict[str, set[str]]  # every known folder, by the slug it maps to

    def resolve(self, token: str) -> list[SessionRecord]:
        """Sessions matching a full ID, an 8+ character prefix, a bridge ID, a job's short ID, or a name.

        Returns every match, so a caller can refuse an ambiguous one rather than guess.
        """
        t = token.strip()
        if t.endswith(".jsonl"):
            t = t[:-6]
        if UUID.match(t.lower()):
            s = self.sessions.get(t.lower())
            return [s] if s else []
        if suffix := bridge_suffix(t):
            return [s for s in self.sessions.values() if any(bridge_suffix(b) == suffix for b in s.bridge_ids)]
        hits = [s for s in self.sessions.values() if len(t) >= 8 and s.session_id.startswith(t.lower())]
        hits += [s for s in self.sessions.values() if t in s.aliases and s not in hits]
        if not hits:
            hits = [s for s in self.sessions.values() if t in s.names[:1]]
        return hits


def _str(d: dict, k: str) -> str | None:
    v = d.get(k)
    return v if isinstance(v, str) else None


def build(fs: ClaudeFS, trust: Trust, machine: Machine | None = None) -> Model:
    machine = machine or Machine.here(fs.home)
    sessions: dict[str, SessionRecord] = {}
    for slug_name, transcript in fs.transcripts():
        sid = transcript.stem
        s = sessions.get(sid)
        if s is None:
            tail = fs.tail_meta(transcript, sid)
            st = transcript.stat()
            s = sessions[sid] = SessionRecord(
                sid,
                [],
                names=names(tail, fs.custom_title_file(slug_name, sid)),
                bridge_ids=tail.bridge_ids,
                first_cwd=fs.first_cwd(transcript),
                size=st.st_size,
                mtime=st.st_mtime,
            )
        s.homes.append(slug_name)

    runs, stale = [], []
    for pf in fs.pid_files():
        if not fs.is_live(pf):
            stale.append(pf)
            continue
        run = Run(
            pf.pid,
            str(pf.get("procStart")),
            pf.session_id or "",
            _str(pf.raw, "kind") or "unknown",
            _str(pf.raw, "status"),
            _str(pf.raw, "cwd"),
            _str(pf.raw, "name"),
            _str(pf.raw, "bridgeSessionId"),
        )
        runs.append(run)
        if s := sessions.get(run.session_id):
            s.runs.append(run)
            if run.name and run.name not in s.names:
                s.names.insert(0, run.name)
            if run.bridge_id:
                s.bridge_ids.add(run.bridge_id)

    jobs = []
    for d, raw in fs.jobs_state():
        job = Job(d.name, _str(raw, "sessionId"), _str(raw, "state"), _str(raw, "cwd"), d)
        jobs.append(job)
        if job.session_id and (s := sessions.get(job.session_id)):
            s.jobs.append(job)
            s.aliases.add(job.short)
            if b := _str(raw, "bridgeSessionId"):
                s.bridge_ids.add(b)

    # Every folder known to the machine, so a slug can be turned back into a folder where exactly
    # one known folder maps to it; a slug is never decoded by guessing.
    folders: dict[str, set[str]] = {}  # by the folder's own slug, for spotting collisions
    filed: dict[str, set[str]] = {}  # by the slug its sessions are filed under, redirects followed
    known = [r.cwd for r in runs] + [j.cwd for j in jobs] + list(fs.claude_json().get("projects", {}) or {})
    known += [s.first_cwd for s in sessions.values()]
    known += [str(a.folder) for a in trust.staff if a.folder]
    for f in known:
        if isinstance(f, str) and f:
            n = os.path.normpath(f)
            folders.setdefault(slug(n), set()).add(n)
            filed.setdefault(fs.filed_slug(n), set()).add(n)
    for s in sessions.values():
        s.staff_file = trust.staff_file(s.session_id)
        if len(s.homes) != 1:
            continue
        # The folder the session itself started in, where it is filed under that folder's slug (a
        # workspace's other folder files under the first folder's); otherwise the one folder known
        # to file there.
        first = os.path.normpath(s.first_cwd) if s.first_cwd else None
        if first and fs.filed_slug(first) == s.homes[0]:
            s.folder = Path(first)
        elif len(cands := filed.get(s.homes[0], set())) == 1:
            s.folder = Path(next(iter(cands)))
    return Model(machine, sessions, runs, stale, jobs, folders)
