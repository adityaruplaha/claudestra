"""The commands that change a session's files: move, rename, trash, restore, purge. Each performs an
action (actions/), which plans, shows the plan, asks at a terminal, and then, inside claudestra's lock,
plans again from a fresh read of the disk and refuses if anything changed while the user was deciding."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table
from rich.text import Text

from ..ops import trash as trash_ops
from . import ui
from .base import FS_CHECKS, Ctx, app, refusing
from .ui import (
    Dry,
    SessionArg,
    SessionsArg,
    Socket,
    Yes,
    ask_folder,
    ask_text,
    complete_entry,
    go_ahead,
    lines,
    out,
    pick,
    session_choices,
)


def _stopped(c: Ctx, keep=lambda s: True) -> list[tuple[str, str]]:
    return session_choices(list(c.model.sessions.values()), c.fs.home, lambda s: not s.runs and keep(s))


@app.command()
def move(
    ctx: typer.Context,
    session: SessionArg = None,
    folder: Annotated[
        Path | None, typer.Argument(file_okay=False, help="The folder to refile it under.", show_default=False)
    ] = None,
    src: Annotated[
        Path | None,
        typer.Option("--from", help="The folder the session is filed under, where its slug alone cannot tell."),
    ] = None,
    exact: Annotated[
        bool,
        typer.Option("--exact", help="Rewrite only the launch folder's cwd, leaving work in its subfolders as it was."),
    ] = False,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Refile a stopped session under FOLDER on this machine, as if it had always run there."""
    c: Ctx = ctx.obj
    c.act(FS_CHECKS)
    s = c.session(session or pick("Which session?", _stopped(c), "a session"))
    dest = (folder or ask_folder("Move it to which folder?", c.fs.home)).expanduser().absolute()
    frm = src.expanduser().absolute() if src else None
    refusing(lambda: s.move(dest, frm, exact).perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("moved", style="green"))


@app.command()
def rename(
    ctx: typer.Context,
    session: SessionArg = None,
    name: Annotated[str | None, typer.Argument(help="The new name.", show_default=False)] = None,
    dry: Dry = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Rename a session as /rename does inside one; one running in claudestra's tmux has /rename typed into it. A staffer's staff file follows."""
    c: Ctx = ctx.obj
    c.act(FS_CHECKS)
    here = session_choices(list(c.model.sessions.values()), c.fs.home, lambda s: bool(s.homes))
    s = c.session(session or pick("Which session?", here, "a session"))
    name = name or ask_text("New name:", "the new name", s.name or "")

    refusing(lambda: s.rename(name, socket).perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("renamed", style="green"))


@app.command()
def trash(
    ctx: typer.Context,
    sessions: SessionsArg = None,
    recent_minutes: Annotated[float, typer.Option(help="Refuse a session written this recently.")] = 10.0,
    list_only: Annotated[bool, typer.Option("--list", "-l", help="List the trash.")] = False,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Move sessions to the trash, every store with them; with --list, or no session off a terminal, show the trash."""
    c: Ctx = ctx.obj
    if list_only or (not sessions and not ui.interactive()):
        t = Table(box=None, header_style="bold", pad_edge=False)
        t.add_column("entry", style="cyan", no_wrap=True)
        t.add_column("title")
        for e, mf in trash_ops.entries(c.fs):
            t.add_row(e.name, (mf.get("title") or "-") if mf else Text("(no manifest)", style="red"))
        out.print(t)
        return
    c.act(FS_CHECKS)
    picked = [
        c.session(t) for t in sessions or [pick("Which session?", _stopped(c, lambda s: not s.staff_file), "a session")]
    ]
    for s in picked:
        refusing(lambda s=s: s.trash(recent_minutes).perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("trashed; `claudestra restore` puts them back", style="green"))


@app.command()
def restore(
    ctx: typer.Context,
    entry: Annotated[
        str | None,
        typer.Argument(
            help="A trash entry, or 8+ characters of its session ID.", autocompletion=complete_entry, show_default=False
        ),
    ] = None,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Put a trashed session back where it came from."""
    c: Ctx = ctx.obj
    entry = entry or pick(
        "Which trash entry?",
        [(e.name, f"{e.name}  {mf.get('title') or '-'}") for e, mf in trash_ops.entries(c.fs) if mf],
        "a trash entry",
    )
    done = refusing(lambda: c.restore(entry).perform(go_ahead(yes, dry)))
    lines(done or [], "green")


@app.command()
def purge(
    ctx: typer.Context,
    older_than: Annotated[
        float, typer.Option("--older-than", metavar="DAYS", help="Delete trash entries older than this.")
    ],
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Delete trash entries older than DAYS, permanently (the user only)."""
    c: Ctx = ctx.obj
    action = c.purge(older_than)
    done = refusing(
        lambda: action.perform(lambda plan: bool(plan) and go_ahead(yes, dry, prompt="Delete these for good?")(plan))
    )
    if not action.doomed:
        out.print("nothing that old in the trash")
    lines(done or [], "red")
