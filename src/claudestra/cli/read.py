"""The reading commands: ls (list), show, summary, whoami, check, audit, doctor. Each takes a
ReadOnlyAction and prints what it returns."""

from __future__ import annotations

import json
from typing import Annotated

import questionary
import typer
from rich.table import Table
from rich.text import Text

from .. import checks
from ..actions.audit import Audit
from ..actions.check import Check
from ..actions.doctor import Doctor
from ..actions.fix_audit import FixAudit
from ..actions.ls import List
from ..actions.permissions import Kinds, Relations, ToFolder
from ..actions.permissions_view import Permissions
from ..actions.whoami import Whoami
from ..ops import remote_control
from ..ops.audit import REPORTS
from ..proctree import describe as describe_chain
from ..trust import tilde
from . import select
from .base import Ctx, app, refusing
from .ui import (
    AsJson,
    Dry,
    Yes,
    go_ahead,
    interactive,
    label,
    lines,
    out,
    state_text,
    when,
    where,
)

ANY = select.Sessions()
ANY_MANY = select.Sessions(many=True, help="Sessions, as for one; picked at a terminal.")


def _tags(c: Ctx, sid: str, s=None) -> Text:
    t = Text()
    scope = c.trust.scope(sid)
    for text, style in (
        (f"{scope} scope" if scope else None, "magenta"),
        ("autostart" if sid in c.trust.autostart(c.machine.hostname) else None, "blue"),
        ("protected" if s and c.trust.is_protected(s.folder, s.homes[0]) else None, "yellow"),
        ("staff" if c.trust.staff_file(sid) else None, "cyan"),
    ):
        if text:
            t.append(("  " if t else "") + text, style=style)
    return t


@app.command("ls")
@app.command("list", hidden=True)
def ls_cmd(
    ctx: typer.Context,
    show_all: Annotated[
        bool, typer.Option("--all", "-a", help="Every session, not only staffers and running ones.")
    ] = False,
    as_json: AsJson = False,
) -> None:
    """Sessions on this machine: staffers and running sessions, or --all. Also `claudestra list`."""
    c: Ctx = ctx.obj
    listing = refusing(List(show_all).perform)
    home = c.fs.home
    rows = [s.record for s in listing.sessions]
    if as_json:
        print(
            json.dumps(
                [
                    {
                        "session": s.session_id,
                        "name": s.name,
                        "staffer": s.staff_file.name if s.staff_file else None,
                        "homes": s.homes,
                        "folder": str(s.folder) if s.folder else None,
                        "state": s.state,
                        "scope": c.trust.scope(s.session_id),
                        "protected": c.trust.is_protected(s.folder, s.homes[0]),
                        "last_active": when(s.mtime),
                    }
                    for s in rows
                ]
                + [  # running, with no transcript yet, as the table shows them
                    {
                        "session": r.session_id,
                        "name": r.name,
                        "folder": r.cwd,
                        "state": f"{r.kind} {r.status or ''}".strip(),
                        "transcript": False,
                    }
                    for r in listing.unwritten
                ],
                indent=2,
            )
        )
        return
    t = Table(
        title=f"{c.machine.hostname}: {listing.total} sessions, {listing.running} running",
        title_justify="left",
        caption=None if show_all else "staffers and running sessions; --all for every one",
        caption_justify="left",
        header_style="bold",
        box=None,
        pad_edge=False,
    )
    t.add_column("session", style="cyan", no_wrap=True)
    t.add_column("name", style="bold")
    t.add_column("state")
    t.add_column("folder", no_wrap=True)
    t.add_column("last active", style="dim", no_wrap=True)
    t.add_column("")
    for s in rows:
        t.add_row(s.session_id[:8], label(s), state_text(s), where(s, home), when(s.mtime), _tags(c, s.session_id, s))
    for a in listing.elsewhere:
        t.add_row(
            a.session[:8],
            a.name,
            Text(f"not on {c.machine.hostname}", style="dim"),
            tilde(a.folder, home),
            "-",
            _tags(c, a.session),
        )
    for r in listing.unwritten:  # counted as running, so shown: a session that has not written a transcript yet
        t.add_row(
            r.session_id[:8],
            r.name or "-",
            Text(f"{r.kind} {r.status or ''} (pid {r.pid}), no transcript yet".replace("  ", " "), style="yellow"),
            tilde(r.cwd, home) if r.cwd else "-",
            "-",
            "",
        )
    out.print(t)


@app.command()
def show(ctx: typer.Context, session: ANY.arg = None, as_json: AsJson = False) -> None:
    """One session in full."""
    session = ANY.get(session)
    info = refusing(session.show().perform)
    s = session.record
    if as_json:
        print(json.dumps(info, indent=2, default=str))
        return
    t = Table.grid(padding=(0, 2))
    t.add_column(style="bold", no_wrap=True)
    t.add_column(overflow="fold")
    for k, v in info.items():
        if v in (None, [], {}, ""):
            continue
        if isinstance(v, dict):
            v = "\n".join(f"{kk}: {vv}" for kk, vv in v.items())
        elif isinstance(v, list):
            v = "\n".join(str(x) for x in v)
        t.add_row(
            k.replace("_", " "),
            state_text(s) if k == "state" else Text(str(v), style="red" if k == "drop_in_problem" else ""),
        )
    out.print(t)


@app.command()
def summary(
    ctx: typer.Context,
    sessions: ANY_MANY.arg = None,
    reply_chars: Annotated[int, typer.Option(help="How much of the last reply to show.")] = 1500,
    as_json: AsJson = False,
) -> None:
    """Is a session finished? Its typed prompts, what was relayed, and its last reply."""
    c: Ctx = ctx.obj
    picked = ANY_MANY.get(sessions)
    if as_json:
        rows = []
        for session in picked:
            sm = refusing(session.summary(reply_chars).perform)
            s = session.record
            rows.append(
                {
                    "session": s.session_id,
                    "name": s.name,
                    "state": s.state,
                    "typed": sm.typed,
                    "relayed": sm.relayed,
                    "last_reply": sm.last_reply[:reply_chars],
                }
            )
        print(json.dumps(rows, indent=2))
        return
    for session in picked:
        sm = refusing(session.summary(reply_chars).perform)
        s = session.record
        out.rule(
            Text(s.session_id, style="cyan") + Text(f"  {s.name or '(untitled)'}  ", style="bold") + state_text(s),
            align="left",
        )
        out.print(Text(where(s, c.fs.home), style="dim"))
        out.print(
            f"{len(sm.typed)} typed prompts; relayed: "
            + (", ".join(f"{n} {k}" for k, n in sorted(sm.relayed.items())) or "none")
        )
        for p in sm.typed:
            out.print(Text("> ", style="bold green") + Text(p[:220]))
        out.print(Text("last reply: ", style="bold") + Text(sm.last_reply[:reply_chars].replace("\n", " ")))
        out.print()


@app.command()
def whoami(
    ctx: typer.Context,
    chain: Annotated[
        bool, typer.Option("--chain", help="Also print the process chain claudestra judged the caller by.")
    ] = False,
    as_json: AsJson = False,
) -> None:
    """The caller, as the process chain shows it, whether it runs under Claude, and what it may do."""
    c: Ctx = ctx.obj
    if as_json:
        me = refusing(Whoami().perform)
        sub = me.subject
        print(
            json.dumps(
                {
                    "kind": sub.kind,
                    "session": sub.session,
                    "name": sub.name,
                    "describe": sub.describe(),
                    "folder": str(sub.folder) if sub.folder else None,
                    "restricted": me.restricted,
                    "chain": [p.describe() for p in me.chain],
                    "managed_by": me.managed_by,
                    "may": me.may,
                    "spawn_and_hire": me.spawn_in,
                },
                indent=2,
            )
        )
        return
    if chain:
        for line in describe_chain(c.fs):
            out.print(Text(line, style="bold" if "session" in line else "dim"))
    me = refusing(Whoami().perform)
    out.print(Text(me.subject.describe(), style="bold"))
    if me.chain:  # restricted mode is announced before every command; here, every Claude process found
        out.print(Text("Claude processes in the chain, nearest first:", style="bold"))
        for p in me.chain:
            out.print(Text("    " + p.describe()))
    if me.subject.kind == "folder":
        out.print(
            Text(f"folder: {me.subject.folder}")
            if me.subject.folder
            else Text(f"folder: none, because {me.subject.note}", style="red")
        )
    if me.managed_by is not None:
        out.print(Text("managed by: ", style="bold") + Text(me.managed_by))
    for verb, names in me.may.items():
        out.print(
            Text(f"may {verb}: ", style="bold") + Text(", ".join(names) or "nothing", style="green" if names else "dim")
        )
    out.print(Text("may spawn and hire: ", style="bold") + Text(me.spawn_in))


@app.command()
def check(ctx: typer.Context, as_json: AsJson = False) -> None:
    """trust.yaml and staff.d/ against this machine."""
    problems, warnings = refusing(Check().perform)
    if as_json:
        print(json.dumps({"errors": problems, "warnings": warnings}, indent=2))
        raise typer.Exit(1 if problems else 0)
    for p in problems:
        out.print(Text("error    ", style="bold red") + Text(p))
    for w in warnings:
        out.print(Text("warning  ", style="yellow") + Text(w))
    if not problems and not warnings:
        out.print(Text("no problems", style="green"))
    raise typer.Exit(1 if problems else 0)


def _choice(options) -> callable:
    return lambda incomplete: [o for o in options if o.startswith(incomplete)]


@app.command()
def audit(
    ctx: typer.Context,
    reports: Annotated[
        list[str] | None,
        typer.Argument(
            help=f"Reports to run: {', '.join(REPORTS)}. Default: all.",
            autocompletion=_choice(REPORTS),
            show_default=False,
        ),
    ] = None,
    fix: Annotated[
        bool,
        typer.Option(
            "--fix", help="Fix the trivial drift found: staffers' staff file names following their sessions' titles."
        ),
    ] = False,
    dry: Dry = False,
    yes: Yes = False,
    as_json: AsJson = False,
) -> None:
    """What needs attention: forks, subagent copies, links, redirects, orphans, stale state. Read-only."""
    found = 0
    result = refusing(Audit(reports).perform)
    if as_json and not fix:
        print(
            json.dumps(
                {
                    n: [{"subject": f.subject, "detail": f.detail, "kind": type(f).__name__} for f in fs]
                    for n, fs in result.items()
                },
                indent=2,
            )
        )
        raise typer.Exit(1 if any(result.values()) else 0)
    for name, findings in result.items():
        found += len(findings)
        out.print(
            Text(f"{name:<10} ", style="bold")
            + (Text("none", style="green") if not findings else Text(str(len(findings)), style="bold yellow"))
        )
        for f in findings:
            out.print(Text("    ") + Text(f.subject, style="cyan") + Text(f"  {f.detail}"))
    if fix:
        fixed = refusing(lambda: FixAudit(reports).perform(go_ahead(yes, dry)))
        if fixed:
            out.print(Text(f"fixed {len(fixed)}", style="green"))
            return
    raise typer.Exit(1 if found else 0)


@app.command()
def doctor(
    ctx: typer.Context,
    names: Annotated[
        list[str] | None,
        typer.Argument(
            help=f"Checks to run: {', '.join(checks.CHECKS)}. Default: all.",
            autocompletion=_choice(checks.CHECKS),
            show_default=False,
        ),
    ] = None,
    deep: Annotated[
        bool, typer.Option("--deep", help="Read every record of every transcript, not only heads and tails.")
    ] = False,
    as_json: AsJson = False,
) -> None:
    """Check on this machine every fact about Claude Code's files that claudestra relies on (DESIGN.md §3)."""
    results = refusing(Doctor(names, deep).perform)
    if as_json:
        print(json.dumps([{"name": r.name, "status": r.status, "detail": r.detail} for r in results], indent=2))
        raise typer.Exit(1 if any(r.status == checks.FAIL for r in results) else 0)
    style = {checks.PASS: "green", checks.WARN: "yellow", checks.FAIL: "bold red", checks.NA: "dim"}
    t = Table(box=None, show_header=False, pad_edge=False)
    t.add_column(no_wrap=True)
    t.add_column(style="bold", no_wrap=True)
    t.add_column(overflow="fold")
    for r in results:
        t.add_row(Text(r.status, style=style[r.status]), r.name, r.detail)
    out.print(t)
    if any(r.name == "remote-control" and r.status == checks.FAIL for r in results) and _offer_remote_control(ctx.obj):
        results = [r for r in results if r.name != "remote-control"] + refusing(Doctor(["remote-control"]).perform)
    raise typer.Exit(1 if any(r.status == checks.FAIL for r in results) else 0)


def _offer_remote_control(c: Ctx) -> bool:
    """At the user's terminal, offer to turn Remote Control on where the user's settings can; whether it did."""
    if not interactive() or c.subject.kind != "human" or remote_control.effective(c.fs)[0] is True:
        return False
    if not questionary.confirm("Turn Remote Control on for every session (claudestra install remote-control)?").ask():
        return False
    lines(refusing(lambda: c.enable_remote_control().perform(go_ahead(True, False))) or [], "green")
    return True


@app.command()
def log(
    ctx: typer.Context,
    session: Annotated[
        str | None,
        typer.Argument(help="Only what was done to this session.", autocompletion=ANY.complete, show_default=False),
    ] = None,
    last: Annotated[int, typer.Option("--last", help="How many entries to show, newest last.")] = 50,
    as_json: AsJson = False,
) -> None:
    """What claudestra has done on this machine: who did what to which session, and when."""
    from ..actions.log import Log

    c: Ctx = ctx.obj
    sid = ANY.get(session).id if session else None
    entries = refusing(Log(sid, last).perform)
    if as_json:
        print(json.dumps(entries, indent=2))
        return
    t = Table(box=None, header_style="bold", pad_edge=False)
    for col in ("at", "action", "session", "by", "detail"):
        t.add_column(col, no_wrap=col in ("at", "action", "session"), style="dim" if col == "at" else None)
    for e in entries:
        subject = str(e.get("subject", ""))
        t.add_row(
            str(e.get("at", ""))[:19].replace("T", " "),
            str(e.get("action", "")),
            c.name_of(subject) or subject[:8],
            str(e.get("caller", "")),
            str(e.get("detail", "")),
        )
    out.print(t)


@app.command()
def permissions(as_json: AsJson = False) -> None:
    """Who may take each action: on a session, by the caller's relation to it; otherwise, by the caller's kind."""
    relations, rules = refusing(Permissions().perform)
    if as_json:

        def rule(r) -> dict:
            if isinstance(r, Relations):
                return {"relations": sorted(r.allowed), "to_folder": isinstance(r, ToFolder)}
            if isinstance(r, Kinds):
                return {"kinds": sorted(r.kinds)}
            return {"anyone": r.note}

        print(json.dumps({"relations": relations, "actions": {v: rule(r) for v, r in rules.items()}}, indent=2))
        return
    t = Table(box=None, header_style="bold", pad_edge=False)
    t.add_column("action", style="bold", no_wrap=True)
    for r in relations:
        t.add_column(r, justify="center")
    t.add_column("otherwise, by kind")
    for verb, rule in rules.items():
        if isinstance(rule, Relations):
            yes = [Text("yes", style="green") if r in rule.allowed else Text("-", style="dim") for r in relations]
            t.add_row(verb, *yes, "to the folder it will work in" if isinstance(rule, ToFolder) else "")
        elif isinstance(rule, Kinds):
            kinds = " or ".join({"human": "the user", "device": "device scope"}.get(k, k) for k in sorted(rule.kinds))
            t.add_row(verb, *("" for _ in relations), kinds)
        else:
            t.add_row(verb, *("" for _ in relations), rule.note)
    out.print(t)
