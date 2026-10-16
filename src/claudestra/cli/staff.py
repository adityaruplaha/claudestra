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
from . import select
from .base import Ctx, app, refusing, session_app, staff_app
from .ui import (
    AsJson,
    Dry,
    Force,
    Socket,
    Yes,
    confirmed,
    err,
    fail,
    go_ahead,
    out,
    outcome,
)

ClaudePath = Annotated[
    str | None,
    typer.Option(
        "--claude",
        help="The claude to run, by exact path (the login unit records it); the user's or the login unit's only.",
    ),
]


STARTABLE = select.Sessions(
    running=False, here=True, many=True, help="Staffers' names, or any session's ID; picked at a terminal."
)
STOPPABLE = select.Sessions(running=True, many=True, help="Running sessions, by name or ID; picked at a terminal.")
RESTARTABLE = select.Sessions(here=True, many=True, help="Sessions, by name or ID; picked at a terminal.")
RUNNING = select.Sessions(running=True)
BUSY = select.Sessions(running=True, many=True, help="Running sessions, by name or ID; picked at a terminal.")
STOPPED = select.Sessions(running=False, here=True)
HIRABLE = select.Sessions(staff=False, here=True)
STAFFER = select.Staffers()
SPAWN_IN = select.Folder(message="Spawn it in which folder?", help="The folder it works in; browsed to at a terminal.")
LINE = select.Text("Text:", "the line to type")
DESCRIPTION = select.Text("Description:", "what it works on")


def _sessions(c: Ctx, refs: list[str], autostart: bool, chooser: select.Sessions | None = None) -> list[Session]:
    """The sessions named, or this machine's autostart staffers, or those picked at a terminal."""
    if autostart:
        if refs:
            raise fail("autostart takes no names")
        found = [c.staffer(sid) for sid in c.trust.autostart(c.machine.hostname)]
        if not found:
            raise fail(f"trust.yaml autostarts nothing on {c.machine.hostname}")
        return found
    return (chooser or RESTARTABLE).get(refs or None)


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
        raise fail("refused: the login unit only runs `claudestra autostart`")
    chooser = RESTARTABLE if do_stop and do_start else STOPPABLE if do_stop else STARTABLE
    sessions = _sessions(c, names, autostart, chooser)
    exe = _claude(caller.kind, claude, socket) if do_start else ""
    verb = "restart" if do_stop and do_start else "stop" if do_stop else "start"

    def steps(s: Session) -> list:
        return ([s.stop(force, socket)] if do_stop else []) + ([s.start(exe, socket)] if do_start else [])

    def show(plan: list[str]) -> bool:  # print the plan, and do not run it
        for line in plan:
            out.print(outcome(line))
        return False

    # Every session's plan first, as every changing command shows it; a restart's start is planned once
    # its stop has run, so only the stop is shown for it.
    failed, ready = False, []
    for s in sessions:
        try:
            steps(s)[0].perform(show)
            ready.append(s)
        except Refused as e:
            err.print(Text(f"refused   {c.name_of(s.id) or s.id}: {e}", style="bold red"))
            failed = True
    if dry or not ready:
        if dry:
            out.print(Text("dry run; nothing changed", style="dim"))
        raise typer.Exit(1 if failed else 0)
    confirmed(yes, dry, f"{verb.capitalize()} {', '.join(c.name_of(s.id) or s.id for s in ready)}?")
    for s in ready:
        for action in steps(s):
            try:
                if (line := action.perform()) is not None:
                    out.print(outcome(line))
            except Refused as e:
                err.print(Text(f"refused   {c.name_of(s.id) or s.id}: {e}", style="bold red"))
                failed = True
                break
    raise typer.Exit(1 if failed else 0)


@session_app.command()
def start(
    ctx: typer.Context,
    sessions: STARTABLE.arg = None,
    claude: ClaudePath = None,
    dry: Dry = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Start sessions in claudestra's tmux session: staffers by name, any other session (the user only) by ID."""
    _lifecycle(ctx.obj, sessions or [], dry, False, socket, False, True, yes, False, claude)


@app.command()
def autostart(
    ctx: typer.Context, claude: ClaudePath = None, dry: Dry = False, yes: Yes = False, socket: Socket = None
) -> None:
    """Start this machine's autostart staffers, as trust.yaml lists them; the login unit runs this at login."""
    _lifecycle(ctx.obj, [], dry, False, socket, False, True, yes, True, claude)


@session_app.command()
def stop(
    ctx: typer.Context,
    sessions: STOPPABLE.arg = None,
    dry: Dry = False,
    force: Force = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Stop sessions running in claudestra's tmux; their conversations are kept."""
    _lifecycle(ctx.obj, sessions or [], dry, force, socket, True, False, yes)


@session_app.command()
def restart(
    ctx: typer.Context,
    sessions: RESTARTABLE.arg = None,
    claude: ClaudePath = None,
    dry: Dry = False,
    force: Force = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Stop, then start."""
    _lifecycle(ctx.obj, sessions or [], dry, force, socket, True, True, yes, claude=claude)


@session_app.command("type")
def type_(
    ctx: typer.Context,
    session: RUNNING.arg = None,
    text: Annotated[
        str | None, typer.Argument(help="One line to type; Enter is pressed after it.", show_default=False)
    ] = None,
    dry: Dry = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Type a line into a session running in claudestra's tmux and press Enter (the user's, a device scope's, or its manager's)."""
    s = RUNNING.get(session)
    text = LINE.get(text)
    refusing(lambda: s.type(text, socket).perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("typed", style="green"))


@session_app.command()
def peek(
    ctx: typer.Context,
    session: RUNNING.arg = None,
    lines: Annotated[int, typer.Option("--lines", "-l", help="How many lines of its screen to show.")] = 40,
    socket: Socket = None,
) -> None:
    """Show the screen of a session running in claudestra's tmux, without attaching (anyone)."""
    from ..actions.peek import Peek

    s = RUNNING.get(session)
    for line in refusing(Peek(s, lines, socket).perform):
        print(line)


@session_app.command("wait")
def wait_(
    ctx: typer.Context,
    sessions: BUSY.arg = None,
    timeout: Annotated[float, typer.Option("--timeout", "-t", help="Seconds to wait before giving up.")] = 3600.0,
) -> None:
    """Wait until sessions are idle, or have stopped; exits 1 if any is still busy at the timeout (anyone)."""
    from ..actions.wait_idle import WaitIdle

    picked = BUSY.get(sessions)
    c: Ctx = ctx.obj
    for sid, how in refusing(WaitIdle(picked, timeout).perform).items():
        out.print(Text(f"{how:<9} {c.name_of(sid) or sid}", style="green"))


@session_app.command()
def attach(
    ctx: typer.Context,
    session: select.Windows().arg = None,
    socket: Socket = None,
) -> None:
    """Attach to claudestra's tmux session, at one session's window (the user only). Ctrl-b d detaches."""
    c: Ctx = ctx.obj
    refusing(lambda: c.attach(socket).authorize())  # before any question: it is the user's alone
    sid = select.Windows(socket=socket).get(session)
    refusing(lambda: c.attach(socket, sid, c.name_of(sid) if sid else None).perform())


@session_app.command()
def compact(
    ctx: typer.Context,
    session: STOPPED.arg = None,
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
    s = STOPPED.get(session)
    exe = _claude(caller.kind, claude, socket)
    action = s.compact(exe, instructions, timeout, socket)
    for line in refusing(lambda: action.perform(go_ahead(yes, dry))) or []:
        out.print(outcome(line))


@session_app.command()
def spawn(
    ctx: typer.Context,
    folder: SPAWN_IN.arg = None,
    prompt: Annotated[str | None, typer.Option("--prompt", help="Its first prompt: the brief.")] = None,
    name: Annotated[str | None, typer.Option("--name", help="Its name, shown and used to reach it.")] = None,
    staff: Annotated[bool, typer.Option("--staff", help="Hire it into the folder, as a specialist.")] = False,
    description: Annotated[str | None, typer.Option("--description", help="What it works on, with --staff.")] = None,
    claude: ClaudePath = None,
    dry: Dry = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Begin a new session in a folder, in claudestra's tmux (the user's, anywhere; a device scope's, anywhere on its machine; a manager's, inside its folder)."""
    c: Ctx = ctx.obj
    caller = c.act(["pid-files", "proc-start", "remote-control"])
    folder = SPAWN_IN.get(folder)
    action = c.spawn(folder, _claude(caller.kind, claude, socket), prompt, name, staff, description, socket)
    for line in (refusing(lambda: action.perform(go_ahead(yes, dry))) or "").splitlines():
        out.print(outcome(line) if not line.startswith("session ") else Text(line, style="bold"))


@staff_app.command("list")
def staff_list(
    ctx: typer.Context,
    tree: Annotated[bool, typer.Option("--tree", help="Who manages whom on this machine, as a tree.")] = False,
    as_json: AsJson = False,
) -> None:
    """The staff: each staffer's name, session, scope and folder on this machine; --tree for who manages whom."""
    import json

    from rich.table import Table
    from rich.tree import Tree

    from ..trust import tilde

    c: Ctx = ctx.obj
    t_ = c.trust
    staff = sorted(t_.staff, key=lambda f: f.name)

    def boss(sf) -> str | None:
        """Who it answers to here: its nearest folder manager, else a device scope, else the user (None)."""
        if t_.scope(sf.session) == "device":
            return None
        over = t_.managers_over(sf)
        if over:
            return max(over, key=lambda m: len(m.folder.parts)).session
        devices = [d for d in t_.device_managers() if d.session != sf.session]
        return devices[0].session if devices else None

    here = [sf for sf in staff if sf.folder is not None]
    if as_json:
        rows = [
            {
                "name": sf.name,
                "session": sf.session,
                "scope": t_.scope(sf.session),
                "folder": str(sf.folder) if sf.folder else None,
                "folders": sf.folders,
                "answers_to": boss(sf) if sf.folder else None,
            }
            for sf in staff
        ]
        print(json.dumps(rows, indent=2))
        return
    if tree:
        root = Tree(Text("the user", style="bold"))
        nodes: dict[str | None, Tree] = {None: root}
        pending = list(here)
        while pending:  # parents before children: a boss is placed before those who answer to it
            placed = [sf for sf in pending if boss(sf) in nodes]
            if not placed:  # what is left answers to no one placed, so to the user
                placed = pending
            for sf in placed:
                scope = t_.scope(sf.session)
                label = Text(sf.name, style="bold") + Text(
                    f"  {scope + ' scope, ' if scope else ''}{tilde(sf.folder, c.fs.home)}", style="dim"
                )
                nodes[sf.session] = nodes.get(boss(sf), root).add(label)
            pending = [sf for sf in pending if sf not in placed]
        out.print(root)
        return
    t = Table(box=None, header_style="bold", pad_edge=False)
    for col in ("name", "session", "scope", "folder here"):
        t.add_column(col, no_wrap=col != "folder here")
    for sf in staff:
        where_ = tilde(sf.folder, c.fs.home) if sf.folder else Text("(not on this machine)", style="dim")
        t.add_row(sf.name, sf.session[:8], t_.scope(sf.session) or "-", where_)
    out.print(t)


@staff_app.command()
def hire(
    ctx: typer.Context,
    session: HIRABLE.arg = None,
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
    s = HIRABLE.get(session)
    action = s.hire(name, folder, description)
    try:
        action.check()
    except Refused as e:
        if description or "description" not in str(e):
            raise fail(f"refused: {e}") from None
        action.description = DESCRIPTION.get()
    refusing(lambda: action.perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("hired; `claudestra staff dismiss` takes it off the staff", style="green"))


@staff_app.command()
def dismiss(
    ctx: typer.Context,
    staffer: STAFFER.arg = None,
    dry: Dry = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Take a staffer off the staff; its session and any scope are kept, and `claudestra staff hire` brings it back."""
    c: Ctx = ctx.obj
    st = c.staffer(STAFFER.get(staffer))
    refusing(lambda: st.dismiss(socket).perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("dismissed; `claudestra staff hire` brings it back", style="green"))


@staff_app.command()
def describe(
    ctx: typer.Context,
    staffer: STAFFER.arg = None,
    description: Annotated[
        str | None,
        typer.Argument(help="What it works on now; asked for at a terminal if not given.", show_default=False),
    ] = None,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Change what a staffer works on, as its staff file says (whoever may hire it, and the staffer itself)."""
    c: Ctx = ctx.obj
    st = c.staffer(STAFFER.get(staffer))
    description = DESCRIPTION.get(description, st.staff_file.description)
    refusing(lambda: st.set_description(description).perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("described", style="green"))
