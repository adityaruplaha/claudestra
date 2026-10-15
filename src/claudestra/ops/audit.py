"""`claudestra audit`: what needs attention among this machine's sessions. Read-only.

Each report is a list of findings; acting on one is another command's job or the user's.
"""

from __future__ import annotations

import filecmp
import os
from collections.abc import Callable
from pathlib import Path

from ..audit_errors import (
    AuditError,
    BrokenRedirect,
    Fork,
    ManyRuns,
    NameMismatch,
    Orphan,
    OrphanJob,
    SharedSlug,
    Stale,
    StaleConfig,
    SubagentCopy,
    Symlink,
    TwoHomes,
)
from ..claude_fs import KEYED_STORES, MESSAGE_TYPES, UUID, ClaudeFS, prompt_text
from ..model import Model


def forks(fs: ClaudeFS, m: Model) -> list[AuditError]:
    """Sessions that share record uuids: one history copied into several transcripts."""
    owner: dict[str, str] = {}
    parent = {sid: sid for sid in m.sessions}
    entries: dict[str, list[tuple[str, bool]]] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for sid, s in m.sessions.items():
        t = fs.transcript(s.homes[0], sid)
        entries[sid] = [
            (r["uuid"], prompt_text(r) is not None) for r in fs.records(t) if isinstance(r.get("uuid"), str)
        ]
        for uid, _ in entries[sid]:
            if uid in owner:
                parent[find(sid)] = find(owner[uid])
            else:
                owner[uid] = sid
    groups: dict[str, list[str]] = {}
    for sid in m.sessions:
        groups.setdefault(find(sid), []).append(sid)
    out = []
    for members in (g for g in groups.values() if len(g) > 1):
        for sid in sorted(members, key=lambda x: m.sessions[x].mtime):
            others = {u for o in members if o != sid for u, _ in entries[o]}
            own = [(u, typed) for u, typed in entries[sid] if u not in others]
            name = m.sessions[sid].name or "-"
            out.append(
                Fork(
                    sid,
                    f"group of {len(members)}; {name!r}: {len(entries[sid])} records, {len(own)} its own, {sum(t for _, t in own)} of them typed by the user",
                )
            )
    return out


def subagents(fs: ClaudeFS, m: Model) -> list[AuditError]:
    """Subagent transcripts whose records end under another session: a copy a resume or fork left.

    A subagent begun under an earlier ID of a resumed session still ends under its parent's, so only
    the last message record is compared.
    """
    out = []
    for slug_name, d in fs.session_dirs():
        for t in fs.subagents(slug_name, d.name):
            last = next((r for r in reversed(fs.tail_records(t, 64 * 1024)) if r.get("type") in MESSAGE_TYPES), None)
            owner = last.get("sessionId") if last else None
            if not isinstance(owner, str) or owner == d.name:
                continue
            if t.is_symlink():
                continue  # a link is `links`' to report, and Claude Code makes these on purpose
            twins = [
                p
                for p in fs.projects.glob(f"*/{owner}/subagents/{t.name}")
                if not p.is_symlink() and filecmp.cmp(p, t, shallow=False)
            ]
            links = [
                p
                for p in fs.projects.glob(f"*/{owner}/subagents/{t.name}")
                if p.is_symlink() and p.resolve() == t.resolve()
            ]
            where = (
                f"; {owner[:8]} reads it through a symlink"
                if links
                else f"; a real, identical copy is under {owner[:8]}"
                if twins
                else ""
                if owner in m.sessions
                else f"; {owner[:8]} has no transcript here"
            )
            out.append(
                SubagentCopy(
                    f"{d.name}/subagents/{t.name}",
                    f"its records end under {owner}, not this session{where}; see DESIGN.md §9 on forks",
                )
            )
    return out


def links(fs: ClaudeFS, m: Model) -> list[AuditError]:
    """Symlinks in the session stores: dangling ones are a problem, and any link marks a file two
    sessions share, which trash, move and send refuse to split."""
    out = []
    for link, target, dangling in fs.links():
        rel = link.relative_to(fs.root)
        out.append(Symlink(str(rel), f"{'DANGLING ' if dangling else ''}symlink to {target}"))
    return out


def redirects(fs: ClaudeFS, m: Model) -> list[AuditError]:
    """`.session-aliases` redirects whose target slug is gone, or holds neither sessions nor memory:
    left behind when a workspace's first folder moved or was renamed."""
    out = []
    for slug_name, target in fs.redirects():
        t = Path(target)
        if not t.is_dir():
            out.append(BrokenRedirect(slug_name, f"redirects to {target}, which does not exist"))
        elif not any(t.glob("*.jsonl")) and not (t / "memory").is_dir():
            out.append(BrokenRedirect(slug_name, f"redirects to {t.name}, which holds no sessions and no memory"))
    return out


def two_homes(fs: ClaudeFS, m: Model) -> list[AuditError]:
    """A session filed under more than one slug, which `claude --resume` then cannot find."""
    return [
        TwoHomes(s.session_id, f"filed under {', '.join(s.homes)}") for s in m.sessions.values() if len(s.homes) > 1
    ]


def runs(fs: ClaudeFS, m: Model) -> list[AuditError]:
    """More than one live run of a session: a fork in progress."""
    return [
        ManyRuns(s.session_id, f"{len(s.runs)} live runs: pids {', '.join(str(r.pid) for r in s.runs)}")
        for s in m.sessions.values()
        if len(s.runs) > 1
    ]


def orphans(fs: ClaudeFS, m: Model) -> list[AuditError]:
    """Leftovers with no transcript: session folders, keyed store entries, set-aside copies."""
    out = []
    for slug_name, d in fs.session_dirs():
        if not (d.parent / f"{d.name}.jsonl").exists():
            s = m.sessions.get(d.name)
            note = f"; its transcript is under {', '.join(s.homes)}, so this is a split session to merge" if s else ""
            out.append(Orphan(f"{slug_name}/{d.name}", f"session folder with no transcript beside it{note}"))
    # session-env/ also holds folders of runs that never wrote a transcript, so it is not reported.
    for store in (s_ for s_ in KEYED_STORES if s_ != "session-env"):
        for d in fs.keyed_dirs(store):
            if d.name not in m.sessions:
                out.append(Orphan(f"{store}/{d.name}", "no transcript on this machine"))
    for slug_name, f, sid in fs.set_aside():
        out.append(
            Orphan(
                f"{slug_name}/{f.name}",
                "a copy Claude Code set aside" + ("" if sid in m.sessions else ", for a session with no transcript"),
            )
        )
    if fs.projects.is_dir():
        for d in sorted(fs.projects.iterdir()):
            # A memory/ folder, even an empty one, is where auto-memory for that folder goes (and may
            # be a configured auto-memory folder), so only a project folder without one is left over.
            # A `.session-aliases` redirect marks a workspace's other folder, whose sessions are filed
            # under the first folder's slug, so a folder holding one is not left over.
            if (
                d.is_dir()
                and not any(d.glob("*.jsonl"))
                and not (d / "memory").is_dir()
                and not (d / ".session-aliases").is_file()
            ):
                out.append(Orphan(d.name, "project folder with no sessions, no memory folder and no redirect"))
    return out


def stale(fs: ClaudeFS, m: Model) -> list[AuditError]:
    """Pid files and sockets left by crashed sessions, and keys with no pid file."""
    out = [Stale(pf.path.name, f"session {pf.session_id} no longer runs as pid {pf.pid}") for pf in m.stale_pid_files]
    if fs.sessions.is_dir():
        for k in sorted(fs.sessions.glob("*.key")):
            pid = k.name.split(".", 1)[0]
            # A live `claude mcp serve` writes a key and no pid file, so only a key whose
            # process is gone is left over.
            if pid.isdigit() and not (fs.sessions / f"{pid}.json").exists() and fs.proc_stat(int(pid)) is None:
                out.append(Stale(k.name, "a key whose process is gone"))
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        live = {r.pid for r in m.runs}
        for sock in fs.sockets(Path(runtime)):
            if sock.stem.isdigit() and int(sock.stem) not in live and fs.proc_stat(int(sock.stem)) is None:
                out.append(Stale(str(sock), "messaging socket of a process that is gone"))
    return out


def jobs(fs: ClaudeFS, m: Model) -> list[AuditError]:
    """Background jobs whose cwd is gone or whose session is filed elsewhere, or that lost their session."""
    out = []
    for j in m.jobs:
        s = m.sessions.get(j.session_id or "")
        if s is None:
            out.append(OrphanJob(j.short, f"job ({j.state}) for session {j.session_id}, which has no transcript here"))
        elif j.cwd and not Path(j.cwd).is_dir():
            out.append(
                OrphanJob(
                    j.short,
                    f"job's cwd {j.cwd} no longer exists; the session is filed under {', '.join(s.homes)}",
                )
            )
    return out


def slugs(fs: ClaudeFS, m: Model) -> list[AuditError]:
    """Slugs that several known folders map to, where a session's folder cannot be told from its slug."""
    used = {h for s in m.sessions.values() for h in s.homes}
    return [
        SharedSlug(sl, f"{len(fs_)} folders map to it: {', '.join(sorted(fs_))}")
        for sl, fs_ in sorted(m.folders_by_slug.items())
        if len(fs_) > 1 and sl in used
    ]


def config(fs: ClaudeFS, m: Model) -> list[AuditError]:
    """~/.claude.json project entries whose folder is gone, and lastSessionIds with no transcript."""
    out = []
    for path, entry in (fs.claude_json().get("projects", {}) or {}).items():
        if not Path(path).is_dir():
            out.append(StaleConfig(path, "~/.claude.json entry for a folder that is gone"))
        last = entry.get("lastSessionId") if isinstance(entry, dict) else None
        if isinstance(last, str) and UUID.match(last) and last not in m.sessions:
            out.append(StaleConfig(path, f"lastSessionId {last} has no transcript"))
    return out


def names(fs: ClaudeFS, m: Model) -> list[AuditError]:
    """Staffers whose staff file name is not their session's title, as after a /rename inside the session.
    `audit --fix` brings the staff file into step."""
    return [
        NameMismatch(s.session_id, f"staff file says {s.staff_file.name!r}, the session is titled {s.name!r}")
        for s in m.sessions.values()
        if s.staff_file and s.name and s.staff_file.name != s.name
    ]


REPORTS: dict[str, Callable[[ClaudeFS, Model], list[AuditError]]] = {
    "names": names,
    "two-homes": two_homes,
    "runs": runs,
    "forks": forks,
    "subagents": subagents,
    "links": links,
    "redirects": redirects,
    "orphans": orphans,
    "stale": stale,
    "jobs": jobs,
    "slugs": slugs,
    "config": config,
}
