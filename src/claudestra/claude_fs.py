"""Read-only readers of Claude Code's files under ~/.claude, the only module that knows their format.

The format is Claude Code's own and unversioned (DESIGN.md §3), so everything here reads defensively:
a missing field is None, an unreadable line or file is skipped, and what is not recognised is
collected for `doctor` rather than raised. Nothing here writes. The jobs both machines do on these
files (slugs, redirects, liveness) are in portable.py.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from . import portable
from .portable import ALIASES, read_json

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# The Claude Code versions whose files this module has been checked against.
KNOWN_VERSIONS = ("2.1.295", "2.1.296")
# Record types seen in transcripts (DESIGN.md §3); anything else is reported by `doctor`.
KNOWN_RECORD_TYPES = frozenset(
    {
        "user",
        "assistant",
        "system",
        "attachment",
        "summary",
        "last-prompt",
        "bridge-session",
        "agent-name",
        "ai-title",
        "custom-title",
        "mode",
        "permission-mode",
        "atis-latch",
        "queue-operation",
        "file-history-snapshot",
        "file-history-delta",
        "cost-state",
        "pr-link",
        "frame-link",
        "artifact-autoreact-ledger",
        "artifact-comment-monitor",
        "continued-in",
        "fork-context-ref",
    }
)
# The records that carry a conversation's messages, and so `sessionId` and `isSidechain`.
MESSAGE_TYPES = frozenset({"user", "assistant", "attachment"})
# Folders under ~/.claude holding one entry per session ID (DESIGN.md §3). A move or trash carries
# every one that exists.
KEYED_STORES = ("file-history", "session-env", "uploads", "dev-mods", "image-cache")
# Copies Claude Code sets aside beside a transcript; not shown in the picker.
SET_ASIDE = re.compile(r"^(?P<id>[0-9a-f-]{36})(\.orphaned-.+\.jsonl|\.jsonl\.superseded-.+)$")


@dataclass(frozen=True)
class ProcStat:
    ppid: int
    start: str  # field 22 of /proc/<pid>/stat, which Claude Code records as procStart


@dataclass
class PidFile:
    """~/.claude/sessions/<pid>.json: one per running session, as Claude Code wrote it."""

    path: Path
    pid: int
    raw: dict

    def get(self, key: str) -> object:
        return self.raw.get(key)

    @property
    def session_id(self) -> str | None:
        sid = self.raw.get("sessionId")
        return sid if isinstance(sid, str) else None


@dataclass
class TranscriptMeta:
    """What one pass over a transcript tells about its session; last record wins for each name."""

    custom_titles: list[str] = field(default_factory=list)
    agent_names: list[str] = field(default_factory=list)
    ai_titles: list[str] = field(default_factory=list)
    bridge_ids: set[str] = field(default_factory=set)
    secondary_ids: set[str] = field(default_factory=set)
    cwds: dict[str, int] = field(default_factory=dict)
    versions: set[str] = field(default_factory=set)
    origins: dict[str, int] = field(default_factory=dict)  # user records by origin kind
    continued_in: list[str] = field(default_factory=list)  # sessions this one continues in
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    cost_usd: float | None = None
    records: int = 0
    unreadable_lines: int = 0  # -1: the file itself could not be opened
    unknown_types: dict[str, int] = field(default_factory=dict)


class ClaudeFS:
    """Claude Code's files for one user on one machine.

    `home` is the user's home folder and `proc` the /proc to read processes from; tests point both
    at fixture trees.
    """

    def __init__(self, home: Path | None = None, proc: Path = Path("/proc")):
        self.home = home or Path.home()
        self.proc = proc
        self.root = self.home / ".claude"
        self.projects = self.root / "projects"
        self.sessions = self.root / "sessions"
        self.jobs = self.root / "jobs"
        self.config = self.home / ".claude.json"

    def transcript(self, slug_name: str, session_id: str) -> Path:
        return self.projects / slug_name / f"{session_id}.jsonl"

    # --- processes ------------------------------------------------------------------------------

    def proc_stat(self, pid: int) -> ProcStat | None:
        """A process's parent and start time, or None if it is gone."""
        st = portable.proc_stat(self.proc, pid)
        return ProcStat(*st) if st else None

    def pid_files(self) -> list[PidFile]:
        """Every ~/.claude/sessions/<pid>.json, live or left behind by a crash."""
        out = []
        for f in sorted(self.sessions.glob("*.json")):
            if f.stem.isdigit() and isinstance(raw := read_json(f), dict):
                out.append(PidFile(f, int(f.stem), raw))
        return out

    def is_live(self, pf: PidFile) -> bool:
        return portable.live_pid_record(self.sessions, self.proc, pf.pid) is not None

    def live_pid_file(self, pid: int) -> PidFile | None:
        rec = portable.live_pid_record(self.sessions, self.proc, pid)
        return PidFile(self.sessions / f"{pid}.json", pid, rec) if rec else None

    def sockets(self, runtime_dir: Path) -> list[Path]:
        """Messaging sockets under <XDG_RUNTIME_DIR>/cc-socks/, one per session process."""
        d = runtime_dir / "cc-socks"
        return sorted(d.glob("*.sock")) if d.is_dir() else []

    # --- where sessions are filed ---------------------------------------------------------------

    def filed_slug(self, folder: str | Path) -> str:
        return portable.filed_slug(self.projects, folder)

    def redirects(self) -> list[tuple[str, str]]:
        """(slug, target) for each project folder holding a `.session-aliases` redirect (DESIGN.md §3)."""
        out = []
        for f in sorted(self.projects.glob(f"*/{ALIASES}")) if self.projects.is_dir() else []:
            try:
                out.append((f.parent.name, f.read_text().strip()))
            except OSError:
                continue
        return out

    # --- transcripts ----------------------------------------------------------------------------

    def transcripts(self) -> Iterator[tuple[str, Path]]:
        """(slug, transcript) for every session transcript on this machine."""
        for d in sorted(self.projects.iterdir()) if self.projects.is_dir() else []:
            if d.is_dir():
                for t in sorted(d.glob("*.jsonl")):
                    if UUID.match(t.stem):
                        yield d.name, t

    def records(self, transcript: Path) -> Iterator[dict]:
        """Every record of a transcript; nothing for one that cannot be opened (a dangling link)."""
        try:
            fh = transcript.open(errors="replace")
        except OSError:
            return
        with fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict):
                    yield rec

    def head_records(self, transcript: Path, n: int = 40) -> list[dict]:
        out = []
        for rec in self.records(transcript):
            out.append(rec)
            if len(out) >= n:
                break
        return out

    def first_cwd(self, transcript: Path) -> str | None:
        """The folder the session started in: the first cwd its transcript records."""
        return next((r["cwd"] for r in self.head_records(transcript) if isinstance(r.get("cwd"), str)), None)

    def tail_records(self, transcript: Path, nbytes: int = 256 * 1024) -> list[dict]:
        """The records in the last `nbytes` of a transcript, where the re-appended metadata is.

        Cheap on a transcript of hundreds of megabytes, which a full pass is not.
        """
        try:
            fh = transcript.open("rb")
        except OSError:
            return []
        with fh:
            size = fh.seek(0, 2)
            fh.seek(max(0, size - nbytes))
            lines = fh.read().split(b"\n")
        out = []
        for line in lines[1:] if size > nbytes else lines:  # the first of a cut window is partial
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
        return out

    def read_meta(self, transcript: Path, session_id: str) -> TranscriptMeta:
        """Everything a full pass over the transcript tells; see tail_meta for a cheap one."""
        m = TranscriptMeta()
        try:
            fh = transcript.open(errors="replace")
        except OSError:
            m.unreadable_lines = -1
            return m
        with fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except ValueError:
                    r = None
                if isinstance(r, dict):
                    absorb(m, r, session_id)
                else:
                    m.unreadable_lines += 1
        return m

    def tail_meta(self, transcript: Path, session_id: str) -> TranscriptMeta:
        """What the end of a transcript tells, where its re-appended names and bridge IDs are."""
        m = TranscriptMeta()
        for r in self.tail_records(transcript):
            absorb(m, r, session_id)
        return m

    def custom_title_file(self, slug_name: str, session_id: str) -> str | None:
        raw = read_json(self.projects / slug_name / session_id / "custom-title.json")
        title = raw.get("customTitle") if isinstance(raw, dict) else None
        return title if isinstance(title, str) else None

    def subagents(self, slug_name: str, session_id: str) -> list[Path]:
        d = self.projects / slug_name / session_id / "subagents"
        return sorted(d.glob("*.jsonl")) if d.is_dir() else []

    # --- other per-session stores ---------------------------------------------------------------

    def session_dirs(self) -> Iterator[tuple[str, Path]]:
        """(slug, folder) for every <session ID>/ folder under a project, with or without a transcript."""
        for d in sorted(self.projects.iterdir()) if self.projects.is_dir() else []:
            if d.is_dir():
                for s in sorted(d.iterdir()):
                    if s.is_dir() and UUID.match(s.name):
                        yield d.name, s

    def keyed_dirs(self, store: str) -> list[Path]:
        """Entries named by session ID directly under one of the keyed stores."""
        base = self.root / store
        return sorted(p for p in base.iterdir() if p.is_dir() and UUID.match(p.name)) if base.is_dir() else []

    def keyed_entries(
        self, session_id: str, secondary_ids: frozenset[str] | set[str] = frozenset()
    ) -> list[tuple[str, Path]]:
        """(label, path) for every entry under the session's ID, or a secondary one, in the keyed stores."""
        return [
            (f"{store}/{key}", self.root / store / key)
            for store in KEYED_STORES
            for key in (session_id, *sorted(secondary_ids))
            if (self.root / store / key).exists()
        ]

    def jobs_state(self) -> list[tuple[Path, dict]]:
        """(job folder, state.json) for each background job Claude Code's supervisor knows."""
        out = []
        for d in sorted(self.jobs.iterdir()) if self.jobs.is_dir() else []:
            if isinstance(raw := read_json(d / "state.json"), dict):
                out.append((d, raw))
        return out

    def set_aside(self) -> list[tuple[str, Path, str]]:
        """(slug, file, session ID) for each orphaned or superseded copy beside the transcripts."""
        out = []
        for d in sorted(self.projects.iterdir()) if self.projects.is_dir() else []:
            if d.is_dir():
                for f in sorted(d.iterdir()):
                    if f.is_file() and (m := SET_ASIDE.match(f.name)):
                        out.append((d.name, f, m["id"]))
        return out

    def links(self) -> list[tuple[Path, str, bool]]:
        """(link, its target as written, whether it dangles) for every symlink in the session stores (DESIGN.md §3)."""
        out = []
        for base in (self.projects, *(self.root / s for s in KEYED_STORES)):
            for dirpath, dirnames, filenames in os.walk(base) if base.is_dir() else []:
                for name in dirnames + filenames:
                    if (q := Path(dirpath) / name).is_symlink():
                        out.append((q, os.readlink(q), not q.exists()))
        return out

    def claude_json(self) -> dict:
        raw = read_json(self.config)
        return raw if isinstance(raw, dict) else {}


def absorb(m: TranscriptMeta, r: dict, session_id: str) -> None:
    """Fold one record into what is known of its session."""
    m.records += 1
    t = r.get("type")
    if t not in KNOWN_RECORD_TYPES:
        m.unknown_types[str(t)] = m.unknown_types.get(str(t), 0) + 1
    if t == "custom-title" and isinstance(r.get("customTitle"), str):
        m.custom_titles.append(r["customTitle"])
    elif t == "agent-name" and isinstance(r.get("agentName"), str):
        m.agent_names.append(r["agentName"])
    elif t == "ai-title" and isinstance(r.get("aiTitle"), str):
        m.ai_titles.append(r["aiTitle"])
    elif t == "bridge-session" and r.get("bridgeSessionId"):
        m.bridge_ids.add(str(r["bridgeSessionId"]))
    elif t == "continued-in" and isinstance(c := r.get("continuedInSessionId"), str) and c not in m.continued_in:
        m.continued_in.append(c)
    elif t == "cost-state" and isinstance(r.get("totalCostUSD"), int | float):
        m.cost_usd = float(r["totalCostUSD"])
    if isinstance(sec := r.get("session_id"), str) and sec != session_id and UUID.match(sec):
        m.secondary_ids.add(sec)
    if isinstance(cwd := r.get("cwd"), str):
        m.cwds[cwd] = m.cwds.get(cwd, 0) + 1
    if isinstance(v := r.get("version"), str):
        m.versions.add(v)
    if isinstance(ts := r.get("timestamp"), str):
        m.first_timestamp = m.first_timestamp or ts
        m.last_timestamp = ts
    if t == "user":
        kind = origin_kind(r)
        m.origins[kind] = m.origins.get(kind, 0) + 1


def names(m: TranscriptMeta, title_file: str | None) -> list[str]:
    """A session's names, latest first: what /rename set, then Claude Code's generated title."""
    out: list[str] = []
    for n in [
        *reversed(m.custom_titles),
        *([title_file] if title_file else []),
        *reversed(m.agent_names),
        *reversed(m.ai_titles),
    ]:
        if n not in out:
            out.append(n)
    return out


def origin_kind(rec: dict) -> str:
    """Who a user record came from: human, peer, task-notification, scheduled, system, or unknown.

    `origin` is a mapping with a `kind` in recent versions; `turnOrigin` is a plain string and is
    the fallback.
    """
    o = rec.get("origin")
    if isinstance(o, dict) and isinstance(o.get("kind"), str):
        return o["kind"]
    t = rec.get("turnOrigin")
    return t.replace("_", "-") if isinstance(t, str) else "unknown"


def prompt_text(rec: dict) -> str | None:
    """The text of a user record that the user typed, or None for anything else: a tool result, a
    peer's message, a notification, a compaction summary or a meta record."""
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isCompactSummary"):
        return None
    c = rec.get("message", {}).get("content") if isinstance(rec.get("message"), dict) else None
    if isinstance(c, list):
        if any(isinstance(p, dict) and p.get("type") == "tool_result" for p in c):
            return None
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") == "text")
    if not isinstance(c, str) or not c.strip():
        return None
    kind = origin_kind(rec)
    # Older records have no origin; a prompt typed then never starts with a tag.
    return " ".join(c.split()) if kind == "human" or (kind == "unknown" and not c.lstrip().startswith("<")) else None


def bridge_suffix(bridge_id: str) -> str | None:
    """The shared part of a Remote Control ID, which appears as session_<x> and as cse_<x>."""
    for prefix in ("session_", "cse_"):
        if bridge_id.startswith(prefix):
            return bridge_id[len(prefix) :]
    return None


def claude_agents(timeout: float = 20) -> tuple[list[dict] | None, str]:
    """`claude agents --json --all`, the supported view of background sessions, or None and why not."""
    exe = shutil.which("claude")
    if not exe:
        return None, "claude is not on PATH"
    try:
        r = subprocess.run(
            [exe, "agents", "--json", "--all"],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return None, f"claude agents --json --all took longer than {timeout:g}s"
    if r.returncode != 0:
        return None, f"claude agents exited {r.returncode}: {r.stderr.strip()[:200]}"
    try:
        data = json.loads(r.stdout)
    except ValueError:
        return None, "claude agents --json did not print JSON"
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        return None, "claude agents --json did not print a list of objects"
    return data, ""
