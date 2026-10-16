"""`claudestra doctor`: each fact in DESIGN.md §3 that claudestra relies on, checked on this machine.

Every check returns pass, warn, fail, or n/a (nothing on this machine to check it against). A new Claude
Code version that changes a fact shows up here as a failure before an operation acts on it, and a
mutating command runs the checks it depends on first (`require`).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from .caller import Refused
from .claude_fs import (
    KNOWN_RECORD_TYPES,
    KNOWN_VERSIONS,
    MESSAGE_TYPES,
    UUID,
    ClaudeFS,
    bridge_suffix,
    claude_agents,
)
from .model import Machine
from .ops import guard, remote_control, unit
from .trust import Trust, load, machine_problem

# A warning is reported and blocks nothing: what it reports is worth a look, not a reason to refuse.
PASS, WARN, FAIL, NA = "pass", "warn", "fail", "n/a"


@dataclass
class Result:
    name: str
    status: str
    detail: str


def _live(fs: ClaudeFS):
    return [pf for pf in fs.pid_files() if fs.is_live(pf)]


def check_pid_files(fs: ClaudeFS, deep: bool) -> Result:
    """A running session has sessions/<pid>.json with its pid, session ID, cwd and procStart."""
    pfs = fs.pid_files()
    if not pfs:
        return Result("pid-files", NA, "no ~/.claude/sessions/<pid>.json")
    bad = []
    for pf in pfs:
        missing = [k for k in ("pid", "sessionId", "cwd", "procStart", "kind") if k not in pf.raw]
        if missing:
            bad.append(f"{pf.path.name} lacks {', '.join(missing)}")
        elif pf.get("pid") != pf.pid or not UUID.match(str(pf.get("sessionId"))):
            bad.append(f"{pf.path.name}: pid or sessionId malformed")
    return Result(
        "pid-files", FAIL if bad else PASS, "; ".join(bad) or f"{len(pfs)} pid files have the expected fields"
    )


def check_proc_start(fs: ClaudeFS, deep: bool) -> Result:
    """procStart equals field 22 of /proc/<pid>/stat for a running session, so liveness can be told."""
    claude = []
    for pf in fs.pid_files():
        try:
            cmd = (fs.proc / str(pf.pid) / "cmdline").read_bytes()
        except OSError:
            continue
        if b"claude" in cmd:
            claude.append(pf)
    if not claude:
        return Result("proc-start", NA, "no running claude process with a pid file")
    bad = [pf.path.name for pf in claude if not fs.is_live(pf)]
    return Result(
        "proc-start",
        FAIL if bad else PASS,
        f"procStart does not match /proc for {', '.join(bad)}"
        if bad
        else f"{len(claude)} running sessions match /proc",
    )


def check_slug_rule(fs: ClaudeFS, deep: bool) -> Result:
    """A session's transcript is filed under the slug of the folder it started in."""
    seen, bad = 0, []
    for pf in _live(fs):
        sid, cwd = pf.session_id, pf.get("cwd")
        homes = [p.parent.name for p in fs.projects.glob(f"*/{sid}.jsonl")]
        if not homes or not isinstance(cwd, str):
            continue  # a new session has no transcript yet
        seen += 1
        first = fs.first_cwd(fs.transcript(homes[0], sid))
        if fs.filed_slug(first or cwd) not in homes and fs.filed_slug(cwd) not in homes:
            bad.append(f"{sid[:8]} in {cwd} is filed under {', '.join(homes)}")
    if not seen:
        return Result("slug-rule", NA, "no running session with a transcript")
    return Result(
        "slug-rule",
        FAIL if bad else PASS,
        "; ".join(bad) or f"{seen} running sessions are filed under their folder's slug",
    )


def check_transcript_ids(fs: ClaudeFS, deep: bool) -> Result:
    """A main transcript's records carry the session ID its file is named by."""
    n, bad = 0, []
    for slug_name, t in fs.transcripts():
        n += 1
        ids = {
            r["sessionId"]
            for r in (fs.records(t) if deep else fs.head_records(t))
            if isinstance(r.get("sessionId"), str)
        }
        if ids - {t.stem}:
            bad.append(f"{slug_name}/{t.name} holds {', '.join(sorted(ids - {t.stem}))[:80]}")
    if not n:
        return Result("transcript-ids", NA, "no transcripts")
    return Result("transcript-ids", FAIL if bad else PASS, "; ".join(bad[:5]) or f"{n} transcripts carry their own ID")


def check_record_types(fs: ClaudeFS, deep: bool) -> Result:
    """Every record type is one claudestra knows. A warning: a move rewrites `cwd` in a record of any type, so
    a new type matters only if it holds a path under another name, which is worth a look after an update."""
    unknown: dict[str, int] = {}
    n = 0
    for _, t in fs.transcripts():
        n += 1
        for r in fs.records(t) if deep else fs.tail_records(t, 64 * 1024):
            if (ty := str(r.get("type"))) not in KNOWN_RECORD_TYPES:
                unknown[ty] = unknown.get(ty, 0) + 1
    if not n:
        return Result("record-types", NA, "no transcripts")
    where = "all records" if deep else "the tail of each transcript (--deep for all records)"
    return Result(
        "record-types",
        WARN if unknown else PASS,
        f"unknown types {unknown}" if unknown else f"only known types, in {where}",
    )


def check_versions(fs: ClaudeFS, deep: bool) -> Result:
    """The running Claude Code versions are ones these checks were written against. A warning, since Claude
    Code updates every few days; the checks that matter fail on their own if a fact has changed."""
    vs = {str(pf.get("version")) for pf in _live(fs) if pf.get("version")}
    if not vs:
        return Result("versions", NA, "no running session reports a version")
    new = sorted(vs - set(KNOWN_VERSIONS))
    return Result(
        "versions",
        WARN if new else PASS,
        f"unchecked versions {', '.join(new)}: read every other result with that in mind"
        if new
        else f"running {', '.join(sorted(vs))}",
    )


def check_env_session(fs: ClaudeFS, deep: bool) -> Result:
    """CLAUDE_CODE_SESSION_ID in a session's children names that session, as the docs say. A warning, since
    claudestra identifies its caller from the process chain, never from this variable (DESIGN.md §6.4)."""
    env = os.environ.get("CLAUDE_CODE_SESSION_ID")
    pid = os.getppid()
    while pid > 1:
        if pf := fs.live_pid_file(pid):
            if env is None:
                return Result(
                    "env-session-id",
                    WARN,
                    f"running under session {pf.session_id} but CLAUDE_CODE_SESSION_ID is not set",
                )
            ok = env == pf.session_id
            return Result(
                "env-session-id",
                PASS if ok else WARN,
                "matches the process tree"
                if ok
                else f"environment says {env}, the process tree {pf.session_id} (after /clear or a bare --resume this is expected)",
            )
        st = fs.proc_stat(pid)
        if st is None:
            break
        pid = st.ppid
    return Result("env-session-id", NA, "not running under a Claude session")


def check_bridge_ids(fs: ClaudeFS, deep: bool) -> Result:
    """A pid file's session_<x> and its transcript's cse_<x> share their suffix. A warning: only finding a
    session by its Remote Control ID relies on it, and a mismatch makes that miss rather than find another."""
    seen, bad = 0, []
    for pf in _live(fs):
        b = pf.get("bridgeSessionId")
        homes = list(fs.projects.glob(f"*/{pf.session_id}.jsonl"))
        if not isinstance(b, str) or not b or not homes:
            continue
        cse = {
            str(r["bridgeSessionId"])
            for r in fs.tail_records(homes[0])
            if r.get("type") == "bridge-session" and r.get("bridgeSessionId")
        }
        if not cse:
            continue
        seen += 1
        if bridge_suffix(b) not in {bridge_suffix(c) for c in cse}:
            bad.append(f"{pf.session_id[:8]}: {b} vs {', '.join(sorted(cse))}")
    if not seen:
        return Result("bridge-ids", NA, "no running Remote Control session with bridge records")
    return Result("bridge-ids", WARN if bad else PASS, "; ".join(bad) or f"{seen} sessions' two bridge forms agree")


def check_subagents(fs: ClaudeFS, deep: bool) -> Result:
    """Subagent transcripts are sidechains whose records carry a session ID.

    Only message records count: a forked subagent's file opens with a fork-context-ref record that
    has neither field. A warning: only `claudestra audit subagents`, which reports, relies on it. Which
    session a subagent's records belong to is `claudestra audit subagents`' concern,
    since a resume or fork can leave a copy under another session.
    """
    n, bad = 0, []
    for _, d in fs.session_dirs():
        for t in fs.subagents(d.parent.name, d.name):
            if not t.exists():
                continue  # a dangling symlink, which `claudestra audit links` reports
            n += 1
            msgs = [
                r
                for r in (fs.records(t) if deep else [*fs.head_records(t, 10), *fs.tail_records(t, 64 * 1024)])
                if r.get("type") in MESSAGE_TYPES
            ]
            if not msgs or any(
                r.get("isSidechain") is not True or not UUID.match(str(r.get("sessionId"))) for r in msgs
            ):
                bad.append(f"{d.name[:8]}/{t.name}")
    if not n:
        return Result("subagents", NA, "no subagent transcripts")
    return Result(
        "subagents",
        WARN if bad else PASS,
        "; ".join(bad[:5]) or f"{n} subagent transcripts are sidechains with session IDs",
    )


def check_jobs(fs: ClaudeFS, deep: bool) -> Result:
    """A background job's folder is named by the first 8 characters of its session ID."""
    jobs = fs.jobs_state()
    if not jobs:
        return Result("jobs", NA, "no ~/.claude/jobs/*/state.json")
    bad = [
        d.name
        for d, raw in jobs
        if not (isinstance(raw.get("sessionId"), str) and raw["sessionId"][:8] == d.name and "cwd" in raw)
    ]
    return Result(
        "jobs",
        FAIL if bad else PASS,
        f"unexpected job state in {', '.join(bad)}" if bad else f"{len(jobs)} jobs named by their session",
    )


def check_claude_agents(fs: ClaudeFS, deep: bool) -> Result:
    """`claude agents --json --all` runs and lists sessions with the documented fields. A warning, since
    nothing in claudestra relies on it yet."""
    data, why = claude_agents()
    if data is None:
        return Result("claude-agents", WARN, why)
    missing = sorted({k for x in data for k in ("sessionId", "kind", "cwd") if k not in x})
    return Result(
        "claude-agents",
        WARN if missing else PASS,
        f"entries lack {', '.join(missing)}" if missing else f"{len(data)} entries",
    )


def check_machine(fs: ClaudeFS, deep: bool, trust: Trust, machine: Machine) -> Result:
    """This machine is the one trust.yaml describes under its hostname, by claudestra's derived ID."""
    why = machine_problem(machine.hostname, machine.machine_id, trust.machines)
    return Result("machine", FAIL if why else PASS, why or f"{machine.hostname} matches trust.yaml")


def check_login_unit(fs: ClaudeFS, deep: bool, trust: Trust, machine: Machine) -> Result:
    """claudestra's login unit is installed and current wherever this machine has sessions to autostart."""
    if not trust.autostart(machine.hostname):
        return Result("login-unit", NA, f"trust.yaml autostarts nothing on {machine.hostname}")
    path = unit.unit_path()
    if not path.is_file():
        return Result(
            "login-unit",
            FAIL,
            f"{path.name} is not installed; propose `claudestra install login-unit` to the user",
        )
    try:
        want = unit.expected()
    except Refused as e:
        return Result("login-unit", FAIL, str(e))
    if path.read_text() != want:
        return Result(
            "login-unit",
            FAIL,
            f"{path} differs from what claudestra would write (claudestra has changed it, or claudestra or claude has moved); propose `claudestra install login-unit` to the user",
        )
    return Result("login-unit", PASS, f"{path.name} is installed and current")


def check_guard(fs: ClaudeFS, deep: bool, trust: Trust, machine: Machine) -> Result:
    """Claude Code's settings keep sessions out of claudestra's config: the deny rules and the hook (DESIGN.md §6.5)."""
    if missing := guard.missing(fs, trust.config):
        return Result("guard", FAIL, f"missing: {'; '.join(missing)}; run `claudestra install guard`")
    return Result("guard", PASS, "sessions are kept out of the config folder")


def check_remote_control(fs: ClaudeFS, deep: bool, trust: Trust, machine: Machine) -> Result:
    """Every session here starts with Remote Control, which claudestra requires (DESIGN.md §7.1): on in the
    user's or managed settings, and off in no staffer's folder on this machine."""
    folders = [sf.folder for sf in trust.staff if sf.folder is not None]
    if why := remote_control.problems(fs, folders):
        fix = (
            "; propose `claudestra install remote-control` to the user"
            if remote_control.effective(fs)[0] is not True
            else ""
        )
        return Result("remote-control", FAIL, "; ".join(why) + fix)
    return Result("remote-control", PASS, f"on for every session, by {remote_control.effective(fs)[1]}")


# The checks that read the config, given it by run() so that --home and --config reach them.
NEEDS_CONFIG = ("machine", "login-unit", "guard", "remote-control")


CHECKS: dict[str, Callable[..., Result]] = {
    "machine": check_machine,
    "login-unit": check_login_unit,
    "guard": check_guard,
    "remote-control": check_remote_control,
    "versions": check_versions,
    "pid-files": check_pid_files,
    "proc-start": check_proc_start,
    "slug-rule": check_slug_rule,
    "transcript-ids": check_transcript_ids,
    "record-types": check_record_types,
    "env-session-id": check_env_session,
    "bridge-ids": check_bridge_ids,
    "subagents": check_subagents,
    "jobs": check_jobs,
    "claude-agents": check_claude_agents,
}


def run(
    fs: ClaudeFS,
    names: list[str] | None = None,
    deep: bool = False,
    trust: Trust | None = None,
    machine: Machine | None = None,
) -> list[Result]:
    machine = machine or Machine.here(fs.home)
    trust = trust or load(machine.hostname, fs.home)
    return [
        CHECKS[n](fs, deep, trust, machine) if n in NEEDS_CONFIG else CHECKS[n](fs, deep)
        for n in (CHECKS if names is None else names)
    ]


def require(fs: ClaudeFS, names: list[str]) -> list[Result]:
    """The named checks that fail; an operation that depends on them refuses if any do."""
    return [r for r in run(fs, names) if r.status == FAIL]
