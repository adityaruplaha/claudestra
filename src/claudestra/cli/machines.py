"""The commands that reach beyond this machine's sessions: send, fetch, install-systemd-user-unit,
install-guard, completion."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import questionary
import typer
from rich.text import Text
from typer._completion_shared import get_completion_script

from ..caller import Refused
from ..ops import guard as guard_ops
from . import ui
from .base import FS_CHECKS, Ctx, app, refusing
from .ui import (
    Dry,
    HostArg,
    SessionArg,
    Yes,
    ask_text,
    go_ahead,
    lines,
    out,
    pick,
    refused,
    session_choices,
)


def _host(c: Ctx, host: str | None) -> str:
    """The other machine, named or picked."""
    return host or pick(
        "Which machine?",
        [(m.hostname, m.hostname) for m in c.machines.values() if m.hostname.lower() != c.machine.hostname.lower()],
        "a machine",
    )


@app.command()
def send(
    ctx: typer.Context,
    session: SessionArg = None,
    host: HostArg = None,
    dest: Annotated[
        str | None, typer.Option("--to", help="The folder on HOST; default: the staffer's staff file.")
    ] = None,
    src: Annotated[Path | None, typer.Option("--from", help="The folder the session is filed under here.")] = None,
    dry: Dry = False,
) -> None:
    """Move a stopped session from this machine to HOST. The user confirms by typing its ID (DESIGN.md §6.3)."""
    c: Ctx = ctx.obj
    c.act(FS_CHECKS)
    s = c.session(
        session
        or pick(
            "Which session?",
            session_choices(list(c.model.sessions.values()), c.fs.home, lambda s: not s.runs),
            "a session",
        )
    )
    host = _host(c, host)

    def typed_yes(plan: list[str]) -> bool:  # asked before the lock is taken
        lines(plan)
        if dry:
            return False
        out.print(Text(f"This moves {s.id} off {c.machine.hostname}.", style="bold yellow"))
        typed = ui.interactive() and (questionary.text("Type the session's full ID to confirm:").ask() or "").strip()
        if typed != s.id:
            raise refused(Refused("the user did not confirm sending this session off this machine"))
        return True

    if refusing(lambda: s.send(host, dest, src).perform(typed_yes)) is not None:
        out.print(Text("sent; the copy here is in the trash", style="green"))


@app.command()
def fetch(
    ctx: typer.Context,
    session: Annotated[str | None, typer.Argument(help="The session's full ID.", show_default=False)] = None,
    host: HostArg = None,
    src: Annotated[
        str | None,
        typer.Option(
            "--from", help="The folder on HOST the session is filed under; default: the staffer's staff file."
        ),
    ] = None,
    dest: Annotated[
        Path | None, typer.Option("--to", file_okay=False, help="The folder here; default: the staffer's staff file.")
    ] = None,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Move a stopped session from HOST to this machine. SESSION is its full ID."""
    c: Ctx = ctx.obj
    c.act(FS_CHECKS)
    session = (session or ask_text("Session's full ID:", "the session's full ID")).strip()
    host = _host(c, host)
    action = c.fetch(session, host, src, dest.expanduser().absolute() if dest else None)
    if refusing(lambda: action.perform(go_ahead(yes, dry))) is not None:
        out.print(Text("fetched; the copy there is in its trash", style="green"))


@app.command("install-systemd-user-unit")
def install_unit(ctx: typer.Context, dry: Dry = False, yes: Yes = False) -> None:
    """Install the login unit, which runs `claudestra start --autostart` at login (the user only; DESIGN.md §7)."""
    c: Ctx = ctx.obj
    lines(refusing(lambda: c.install_login_unit().perform(go_ahead(yes, dry))) or [], "green")


@app.command("install-guard")
def install_guard(
    ctx: typer.Context,
    managed: Annotated[
        bool, typer.Option("--managed", help="Print a drop-in for managed settings, and how to install it as root.")
    ] = False,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Add the deny rules and the hook that keep sessions out of claudestra's config to Claude Code's user
    settings (anyone, since it only adds protection; DESIGN.md §6.5)."""
    c: Ctx = ctx.obj
    if managed:
        print("\n".join(guard_ops.managed(c.trust.config)))  # unwrapped, to be pasted
        return
    lines(refusing(lambda: c.install_guard().perform(go_ahead(yes, dry))) or [], "green")


@app.command()
def completion(shell: Annotated[str, typer.Argument(help="bash, zsh or fish.")] = "zsh") -> None:
    """Print claudestra's shell completion script; adding it to a shell's startup is the user's."""
    if shell not in ("bash", "zsh", "fish"):
        raise refused(Refused(f"no completion script for {shell!r}; choose bash, zsh or fish"))
    print(get_completion_script(prog_name="claudestra", complete_var="_CLAUDESTRA_COMPLETE", shell=shell))
