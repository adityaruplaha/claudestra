"""The commands that change a session's files: `session move` and `session rename`, and the `trash` group. Each performs an
action (actions/), which plans, shows the plan, asks at a terminal, and then, inside claudestra's lock,
plans again from a fresh read of the disk and refuses if anything changed while the user was deciding."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.table import Table
from rich.text import Text

from ..actions.base import Transaction
from ..ops import trash as trash_ops
from ..portable import given_folder
from . import select
from .base import FS_CHECKS, Ctx, refusing, session_app, trash_app
from .ui import (
    AsJson,
    CopyMemory,
    Dry,
    Socket,
    Yes,
    fail,
    go_ahead,
    lines,
    out,
)

STOPPED = select.Sessions(running=False, here=True)
HERE = select.Sessions(here=True)
TRASHABLE = select.Sessions(
    staff=False, running=False, here=True, many=True, help="Sessions off the staff and stopped; picked at a terminal."
)
ENTRY = select.TrashEntries()
MOVE_TO = select.Folder(
    message="Move it to which folder?", help="The folder to refile it under; browsed to at a terminal."
)
NEW_NAME = select.Text("New name:", "the new name")
AGE = select.Text("Delete entries older than how many days?", "--older-than DAYS", "30")


@session_app.command()
def move(
    ctx: typer.Context,
    session: STOPPED.arg = None,
    folder: MOVE_TO.arg = None,
    src: Annotated[
        Path | None,
        typer.Option("--from", help="The folder the session is filed under, where its slug alone cannot tell."),
    ] = None,
    exact: Annotated[
        bool,
        typer.Option("--exact", help="Rewrite only the launch folder's cwd, leaving work in its subfolders as it was."),
    ] = False,
    copy_memory: CopyMemory = False,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Refile a stopped session under FOLDER on this machine, as if it had always run there."""
    c: Ctx = ctx.obj
    c.act(FS_CHECKS)
    s = STOPPED.get(session)
    dest = MOVE_TO.get(folder)
    frm = given_folder(src) if src else None
    refusing(lambda: s.move(dest, frm, exact, copy_memory).perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("moved", style="green"))


@session_app.command()
def rename(
    ctx: typer.Context,
    session: HERE.arg = None,
    name: Annotated[str | None, typer.Argument(help="The new name.", show_default=False)] = None,
    dry: Dry = False,
    yes: Yes = False,
    socket: Socket = None,
) -> None:
    """Rename a session as /rename does inside one; one running in claudestra's tmux has /rename typed into it. A staffer's staff file follows."""
    c: Ctx = ctx.obj
    c.act(FS_CHECKS)
    s = HERE.get(session)
    name = NEW_NAME.get(name, s.name or "")

    refusing(lambda: s.rename(name, socket).perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("renamed", style="green"))


@trash_app.command("list")
def trash_list(ctx: typer.Context, as_json: AsJson = False) -> None:
    """The trash: each entry and the title of the session in it."""
    c: Ctx = ctx.obj
    if as_json:
        print(json.dumps([{"entry": e.name, "manifest": mf} for e, mf in trash_ops.entries(c.fs)], indent=2))
        return
    t = Table(box=None, header_style="bold", pad_edge=False)
    t.add_column("entry", style="cyan", no_wrap=True)
    t.add_column("title")
    for e, mf in trash_ops.entries(c.fs):
        t.add_row(e.name, (mf.get("title") or "-") if mf else Text("(no manifest)", style="red"))
    out.print(t)


@trash_app.command("add")
def trash(
    ctx: typer.Context,
    sessions: TRASHABLE.arg = None,
    recent_minutes: Annotated[float, typer.Option(help="Refuse a session written this recently.")] = 10.0,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Move sessions to the trash, every store with them."""
    c: Ctx = ctx.obj
    c.act(FS_CHECKS)
    picked = TRASHABLE.get(sessions)
    # All or nothing: one plan and one question, and a refusal for any of them trashes none.
    steps = [s.trash(recent_minutes) for s in picked]
    refusing(lambda: (Transaction(steps) if len(steps) > 1 else steps[0]).perform(go_ahead(yes, dry)))
    if not dry:
        out.print(Text("trashed; `claudestra trash restore` puts them back", style="green"))


@trash_app.command()
def restore(
    ctx: typer.Context,
    entry: ENTRY.arg = None,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Put a trashed session back where it came from."""
    c: Ctx = ctx.obj
    entry = ENTRY.get(entry)
    done = refusing(lambda: c.restore(entry).perform(go_ahead(yes, dry)))
    lines(done or [], "green")


@trash_app.command()
def purge(
    ctx: typer.Context,
    older_than: Annotated[
        float | None,
        typer.Option("--older-than", metavar="DAYS", help="Delete trash entries older than this; asked at a terminal."),
    ] = None,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Delete trash entries older than DAYS, permanently (the user only)."""
    c: Ctx = ctx.obj
    if older_than is None:
        try:
            older_than = float(AGE.get())
        except ValueError:
            raise fail("refused: --older-than is a number of days") from None
    action = c.purge(older_than)
    done = refusing(
        lambda: action.perform(lambda plan: bool(plan) and go_ahead(yes, dry, prompt="Delete these for good?")(plan))
    )
    if not action.doomed:
        out.print("nothing that old in the trash")
    lines(done or [], "red")
