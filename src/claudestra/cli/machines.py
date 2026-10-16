"""`machine send` and `machine fetch`, which move sessions between machines, and the parts `install` puts in
place one at a time: `install login-unit`, `guard`, `remote-control` and `completion`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import questionary
import typer
from rich.text import Text

from ..caller import Refused
from ..ops import completion as completion_ops
from ..ops import guard as guard_ops
from ..portable import given_folder
from . import select, ui
from .base import FS_CHECKS, Ctx, install_app, machine_app, refusing
from .ui import (
    AsJson,
    CopyMemory,
    Dry,
    Yes,
    go_ahead,
    lines,
    out,
    refused,
)

SENDABLE = select.Sessions(running=False, here=True)
OTHER = select.Machines(help="The other machine, as trust.yaml names it; picked at a terminal.")
FETCHABLE = select.Staffers(help="The session's full ID, or a staffer that works on HOST; picked at a terminal.")


@machine_app.command("list")
def machine_list(ctx: typer.Context, as_json: AsJson = False) -> None:
    """The machines trust.yaml describes: home, ssh address, and how many staffers start at login."""
    from rich.table import Table

    c: Ctx = ctx.obj
    if as_json:
        here = c.machine.hostname.lower()
        print(
            json.dumps(
                [
                    {
                        "machine": m.hostname,
                        "this_one": m.hostname.lower() == here,
                        "home": str(m.home),
                        "ssh": m.ssh,
                        "autostart": m.autostart,
                    }
                    for m in c.machines.values()
                ],
                indent=2,
            )
        )
        return
    t = Table(box=None, header_style="bold", pad_edge=False)
    for col in ("machine", "home", "ssh", "autostart"):
        t.add_column(col, no_wrap=True)
    for m in c.machines.values():
        here = " (this one)" if m.hostname.lower() == c.machine.hostname.lower() else ""
        t.add_row(m.hostname + here, str(m.home), m.ssh or "-", str(len(m.autostart)))
    out.print(t)


@machine_app.command()
def send(
    ctx: typer.Context,
    session: SENDABLE.arg = None,
    host: OTHER.arg = None,
    dest: Annotated[
        str | None, typer.Option("--to", help="The folder on HOST; default: the staffer's staff file.")
    ] = None,
    src: Annotated[Path | None, typer.Option("--from", help="The folder the session is filed under here.")] = None,
    copy_memory: CopyMemory = False,
    dry: Dry = False,
) -> None:
    """Move a stopped session from this machine to HOST. The user confirms by typing its ID (DESIGN.md §6.3)."""
    c: Ctx = ctx.obj
    c.act(FS_CHECKS)
    s = SENDABLE.get(session)
    host = OTHER.get(host)

    def typed_yes(plan: list[str]) -> bool:  # asked before the lock is taken
        lines(plan)
        if dry:
            return False
        out.print(Text(f"This moves {s.id} off {c.machine.hostname}.", style="bold yellow"))
        typed = ui.interactive() and (questionary.text("Type the session's full ID to confirm:").ask() or "").strip()
        if typed != s.id:
            raise refused(Refused("the user did not confirm sending this session off this machine"))
        return True

    if refusing(lambda: s.send(host, dest, src, copy_memory).perform(typed_yes)) is not None:
        out.print(Text("sent; the copy here is in the trash", style="green"))


@machine_app.command()
def fetch(
    ctx: typer.Context,
    session: FETCHABLE.arg = None,
    host: OTHER.arg = None,
    src: Annotated[
        str | None,
        typer.Option(
            "--from", help="The folder on HOST the session is filed under; default: the staffer's staff file."
        ),
    ] = None,
    dest: Annotated[
        Path | None, typer.Option("--to", file_okay=False, help="The folder here; default: the staffer's staff file.")
    ] = None,
    copy_memory: CopyMemory = False,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Move a stopped session from HOST to this machine: its full ID, or a staffer that works there (the user only)."""
    c: Ctx = ctx.obj
    c.act(FS_CHECKS)
    host = OTHER.get(host)
    session = FETCHABLE.where(on=host, message=f"Which staffer on {host}?").get(session.strip() if session else None)
    action = c.fetch(session, host, src, given_folder(dest) if dest else None, copy_memory)
    if refusing(lambda: action.perform(go_ahead(yes, dry))) is not None:
        out.print(Text("fetched; the copy there is in its trash", style="green"))


@install_app.command("login-unit")
def install_unit(ctx: typer.Context, dry: Dry = False, yes: Yes = False) -> None:
    """Install the login unit, which runs `claudestra autostart` at login (the user only; DESIGN.md §7)."""
    c: Ctx = ctx.obj
    lines(refusing(lambda: c.install_login_unit().perform(go_ahead(yes, dry))) or [], "green")


@install_app.command("guard")
def install_guard(
    ctx: typer.Context,
    managed: Annotated[
        bool, typer.Option("--managed", help="Print a drop-in for managed settings, and how to install it as root.")
    ] = False,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Keep sessions out of claudestra's config: deny rules and a hook in Claude Code's user settings (anyone)."""
    c: Ctx = ctx.obj
    if managed:
        print("\n".join(guard_ops.managed(c.trust.config)))  # unwrapped, to be pasted
        return
    lines(refusing(lambda: c.install_guard().perform(go_ahead(yes, dry))) or [], "green")


@install_app.command("remote-control")
def enable_remote_control(ctx: typer.Context, dry: Dry = False, yes: Yes = False) -> None:
    """Turn Remote Control on for every session, which claudestra requires (the user only)."""
    c: Ctx = ctx.obj
    lines(refusing(lambda: c.enable_remote_control().perform(go_ahead(yes, dry))) or [], "green")


ShellArg = Annotated[
    str | None, typer.Argument(help="zsh, bash or fish; default: the user's shell.", show_default=False)
]


@install_app.command("completion")
def install_completion(
    ctx: typer.Context,
    shell: ShellArg = None,
    print_only: Annotated[
        bool, typer.Option("--print", help="Print the script instead, for a shell set up by hand.")
    ] = False,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Install completion for claudestra and clost in the user's shell (anyone; the plugin does it at each start)."""
    if print_only:
        shell = shell or completion_ops.user_shell()
        if shell not in completion_ops.SHELLS:
            raise refused(Refused(f"no completion script for {shell!r}; choose zsh, bash or fish"))
        print(completion_ops.script(shell), end="")
        return
    c: Ctx = ctx.obj
    lines(refusing(lambda: c.install_completion(shell).perform(go_ahead(yes, dry))) or [], "green")
