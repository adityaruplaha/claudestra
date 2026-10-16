"""What `claudestra show` and `claudestra check` report, apart from how it is printed. Read-only."""

from __future__ import annotations

from dataclasses import asdict

from ..caller import transcript_problem
from ..claude_fs import ClaudeFS
from ..model import Model, SessionRecord
from ..trust import STAFF_HEADER, Trust, tilde


def session_info(fs: ClaudeFS, trust: Trust, m: Model, s: SessionRecord, host: str, state: str) -> dict:
    """Everything known about one session, as plain data."""
    home = fs.home
    meta = fs.read_meta(fs.transcript(s.homes[0], s.session_id), s.session_id)
    dirs = [fs.projects / h / s.session_id for h in s.homes if (fs.projects / h / s.session_id).is_dir()]
    info = {
        "session": s.session_id,
        "names": s.names,
        "staffer": s.staff_file.name if s.staff_file else None,
        "scope": trust.scope(s.session_id),
        "homes": s.homes,
        "folder": tilde(s.folder, home) if s.folder else None,
        "protected": trust.is_protected(s.folder, s.homes[0]),
        "state": state,
        "runs": [asdict(r) for r in s.runs],
        "jobs": [{"short": j.short, "state": j.state, "cwd": j.cwd} for j in s.jobs],
        "bridge_ids": sorted(s.bridge_ids | meta.bridge_ids),
        "secondary_ids": sorted(meta.secondary_ids),
        "continued_in": [f"{x} ({'here' if x in m.sessions else 'not on this machine'})" for x in meta.continued_in],
        "subagents": len(fs.subagents(s.homes[0], s.session_id)),
        "stores": [tilde(p, home) for p in dirs]
        + [tilde(p, home) for _, p in fs.keyed_entries(s.session_id, meta.secondary_ids)],
        "first_activity": meta.first_timestamp,
        "last_activity": meta.last_timestamp,
        "cwds": {tilde(k, home): v for k, v in sorted(meta.cwds.items(), key=lambda kv: -kv[1])},
        "versions": sorted(meta.versions),
        "user_records_by_origin": meta.origins,
        "cost_usd": meta.cost_usd,
        "records": meta.records,
        "size_bytes": s.size,
        "unknown_record_types": meta.unknown_types,
        "unreadable_lines": meta.unreadable_lines,
    }
    if s.staff_file and (why := transcript_problem(fs, host, s.session_id, s.staff_file.folder)):
        info["drop_in_problem"] = why
    return info


def config_report(fs: ClaudeFS, trust: Trust, host: str) -> tuple[list[str], list[str]]:
    """(problems, warnings) in trust.yaml and staff.d/ against this machine."""
    from . import preferences

    problems, warnings = list(trust.errors), list(trust.warnings)
    warnings += preferences.problems(trust.config)
    for a in trust.staff:
        if a.folder is None:
            continue
        where = f"staff.d/{a.file.name} ({a.name})"
        if not a.folder.is_dir():
            problems.append(f"{where}: folder {a.folder} does not exist on {host}")
        elif why := transcript_problem(fs, host, a.session, a.folder):
            # A session lives on one machine at a time, so having no transcript here is expected
            # for one whose staff file also names the other machine.
            elsewhere = not list(fs.projects.glob(f"*/{a.session}.jsonl")) and len(a.folders) > 1
            (warnings if elsewhere else problems).append(
                f"{where}: {why}" + (", so it lives on another machine or nowhere" if elsewhere else "")
            )
    for sf in trust.staff:
        if not sf.file.read_text().startswith(STAFF_HEADER):
            warnings.append(
                f"staff.d/{sf.file.name} ({sf.name}): not written by claudestra; dismiss it and hire it again to have claudestra write it"
            )
    warnings += [
        f"trust.yaml: protected folder {p} does not exist on {host}" for p in trust.protected if not p.is_dir()
    ]
    return problems, warnings
