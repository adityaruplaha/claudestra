"""The commands that run sessions in claudestra's tmux session (start, stop, restart, type, attach, compact),
and that hire and dismiss staffers.
Staffers are named by their names on the staff; any other session by its ID, and only the user runs one."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Annotated

import typer
from rich.text import Text

from ..caller import Refused
from ..session import Session
from .base import Ctx, app, refusing
from .ui import (
    Dry,
    Force,
    RunArg,
    SessionArg,
    Socket,
    Yes,
    ask_text,
    complete_staffer,
    confirmed,
    err,
    fail,
    go_ahead,
    out,
    outcome,
    pick,
    session_choices,
)

ClaudePath = Annotated[
    str | None,
    typer.Option(
        "--claude",
        help="The claude to run, by exact path (the login unit records it); the user's or the login unit's only.",
    ),
]


def _sessions(c: Ctx, refs: list[str], autostart: bool) -> list[Session]:
    """The sessions named, or this machine's autostart staffers, or one picked from the staff."""
    if autostart:
        if refs:
            raise fail("--autostart takes no names")
        found = [c.staffer(sid) for sid in c.trust.autostart(c.machine.hostname)]
        if not found:
            raise fail(f"trust.yaml autostarts nothing on {c.machine.hostname}")
        return found
    refs = refs or [
        pick(
            "Which staffer?",
            [(sf.name, f"{sf.session[:8]}  {sf.name}") for sf in c.trust.staff if sf.folder],
            "a staffer's name, or any session",
        )
    ]
    return [c.session(r) for r in refs]


def _claude(caller_kind: str, override: str | None, socket: str | None) -> str:
    """The claude to run: --claude from the user or the login unit, a test stand-in on a test socket, or PATH's."""
    if override:
        if caller_kind not in ("human", "login"):
            raise fail("refused: --claude is honoured for the user and the login unit only")
        return override
    if test := os.environ.get("CAM_CLAUDE"):
        if not socket:
            raise fail("refused: CAM_CLAUDE is honoured only with --socket (a test tmux server)")
        return test
    if exe := shutil.which("claude"):
        return exe
    raise fail("claude is not on PATH; give its path with --claude")


def _lifecycle(
    c: Ctx,
    names: list[str],
    dry: bool,
    force: bool,
    socket: str | None,
    do_stop: bool,
    do_start: bool,
    yes: bool,
    autostart: bool = False,
    claude: str | None = None,
) -> None:
    caller = c.act(["pid-files", "proc-start", "slug-rule"])
    if caller.kind == "login" and not (autostart and do_start and not do_stop):
        raise fail("refused: the login unit only runs `claudestra start --autostart`")
    sessions = _sessions(c, names, autostart)
    exe = _claude(caller.kind, claude, socket) if do_start else ""
    verb = "restart" if do_stop and do_start else "stop" if do_stop else "start"
    confirmed(yes, dry, f"{verb.capitalize()} {', '.join(c.name_of(s.id) or s.id for s in sessions)}?")

    def dry_lines(plan: list[str]) -> bool:  # each session's plan, shown only for a dry run
        for line in plan:
            out.print(outcome(line))
        return not dry

    failed = False
    for s in sessions:
        actions = ([s.stop(force, socket)] if do_stop else []) + ([s.start(exe, socket)] if do_start else [])
        for action in actions:
            try:
                if (line := action.perform(dry_lines)) is not None:
                    out.print(outcome(line))
            except Refused as e:
                err.print(Text(f"refused   {c.name_of(s.id) or s.id}: {e}", style="bold red"))
                failed = True
                break
    raise typer.Exit(1 if failed else 0)


@app.command()
def start(
    ctx: typer.Context,
    sessions: RunArg = None,
    autostart: Annotated[
        bool, typer.Option("--autostart", help="Start this machine's autostart sessions, as trust.yaml lists them.")
    ] = False,
    claude: ClaudePath = None,
    dry: Dry = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Start sessions in claudestra's tmux session: staffers by name, any other session (the user only) by ID, or --autostart."""
    _lifecycle(ctx.obj, sessions or [], dry, False, socket, False, True, yes, autostart, claude)


@app.command()
def stop(
    ctx: typer.Context,
    sessions: RunArg = None,
    dry: Dry = False,
    force: Force = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Stop sessions running in claudestra's tmux; their conversations are kept."""
    _lifecycle(ctx.obj, sessions or [], dry, force, socket, True, False, yes)


@app.command()
def restart(
    ctx: typer.Context,
    sessions: RunArg = None,
    claude: ClaudePath = None,
    dry: Dry = False,
    force: Force = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Stop, then start."""
    _lifecycle(ctx.obj, sessions or [], dry, force, socket, True, True, yes, claude=claude)


@app.command("type")
def type_(
    ctx: typer.Context,
    session: Annotated[
        str | None,
        typer.Argument(help="The session: a staffer's name, or an ID or 8+ character prefix.", show_default=False),
    ] = None,
    text: Annotated[
        str | None, typer.Argument(help="One line to type; Enter is pressed after it.", show_default=False)
    ] = None,
    dry: Dry = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Type a line into a session running in claudestra's tmux and press Enter (the user's, a device scope's, or its manager's)."""
    c: Ctx = ctx.obj
    s = _sessions(c, [session] if session else [], False)[0]
    text = text or ask_text("Text:", "the line to type", "")
    refusing(lambda: s.type(text, socket).perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("typed", style="green"))


@app.command()
def attach(ctx: typer.Context, socket: Socket = None) -> None:
    """Attach to claudestra's tmux session (the user only)."""
    c: Ctx = ctx.obj
    refusing(lambda: c.attach(socket).perform())


@app.command()
def compact(
    ctx: typer.Context,
    session: SessionArg = None,
    instructions: Annotated[
        str, typer.Argument(help="What the summary should keep, as /compact takes it.", show_default=False)
    ] = "",
    timeout: Annotated[float, typer.Option(help="Seconds to wait for the compaction.")] = 600.0,
    claude: ClaudePath = None,
    dry: Dry = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Compact a stopped session: resume it in claudestra's tmux, type /compact, stop it. A running one compacts itself."""
    c: Ctx = ctx.obj
    caller = c.act(["pid-files", "proc-start", "slug-rule"])
    s = c.session(
        session
        or pick(
            "Which session?",
            session_choices(list(c.model.sessions.values()), c.fs.home, lambda s: not s.runs),
            "a session",
        )
    )
    exe = _claude(caller.kind, claude, socket)
    action = s.compact(exe, instructions, timeout, socket)
    for line in refusing(lambda: action.perform(go_ahead(yes, dry))) or []:
        out.print(outcome(line))


@app.command()
def hire(
    ctx: typer.Context,
    session: SessionArg = None,
    name: Annotated[str | None, typer.Option("--name", help="Its name on the staff; default: its title.")] = None,
    folder: Annotated[
        Path | None,
        typer.Option("--folder", file_okay=False, help="Where it works on this machine; default: where it is filed."),
    ] = None,
    description: Annotated[
        str | None, typer.Option("--description", help="What it works on; asked for at a terminal if not given.")
    ] = None,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Put a session on the staff, or back on it after a dismissal (the user's; a manager's, into its folder; a device scope's, where no manager is)."""
    c: Ctx = ctx.obj
    s = c.session(
        session
        or pick(
            "Which session?",
            session_choices(list(c.model.sessions.values()), c.fs.home, lambda r: r.staff_file is None),
            "a session",
        )
    )
    action = s.hire(name, folder, description)
    try:
        action.check()
    except Refused as e:
        if description or "description" not in str(e):
            raise fail(f"refused: {e}") from None
        action.description = ask_text("Description:", "what it works on", "")
    refusing(lambda: action.perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("hired; `claudestra dismiss` takes it off the staff", style="green"))


@app.command()
def dismiss(
    ctx: typer.Context,
    staffer: Annotated[
        str | None,
        typer.Argument(help="The staffer, by name or ID.", autocompletion=complete_staffer, show_default=False),
    ] = None,
    dry: Dry = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Take a staffer off the staff; its session and any scope are kept, and `claudestra hire` brings it back."""
    c: Ctx = ctx.obj
    st = c.staffer(
        staffer
        or pick("Which staffer?", [(sf.name, f"{sf.session[:8]}  {sf.name}") for sf in c.trust.staff], "a staffer")
    )
    refusing(lambda: st.dismiss(socket).perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("dismissed; `claudestra hire` brings it back", style="green"))


@app.command()
def describe(
    ctx: typer.Context,
    staffer: Annotated[
        str | None,
        typer.Argument(help="The staffer, by name or ID.", autocompletion=complete_staffer, show_default=False),
    ] = None,
    description: Annotated[
        str | None,
        typer.Argument(help="What it works on now; asked for at a terminal if not given.", show_default=False),
    ] = None,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Change what a staffer works on, as its staff file says (whoever may hire it, and the staffer itself)."""
    c: Ctx = ctx.obj
    st = c.staffer(
        staffer
        or pick("Which staffer?", [(sf.name, f"{sf.session[:8]}  {sf.name}") for sf in c.trust.staff], "a staffer")
    )
    description = description or ask_text("Description:", "what it works on", st.staff_file.description)
    refusing(lambda: st.set_description(description).perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("described", style="green"))
