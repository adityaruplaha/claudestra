"""The Typer app: the context every command gets, the preamble of every command that changes
something, and bare `claudestra`'s menu. The commands are in read.py, staff.py, sessions.py and
machines.py, which register themselves on `app`."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Annotated

import questionary
import typer
from rich.text import Text

from ..actions.base import FS_CHECKS  # noqa: F401 - the commands import it from here
from ..caller import Caller, Refused
from ..context import Context
from ..model import Model
from . import ui
from .ui import fail, out

app = typer.Typer(
    help="claudestra: run long-lived Claude Code sessions as a staff, with a chain of command (DESIGN.md). Bare `claudestra` at a terminal opens a menu.",
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_show_locals=False,
    add_completion=False,  # `claudestra completion` prints the script; installing it is the user's
)


class Ctx:
    """The command line's view of the context (claudestra.context): its attributes, with a refusal
    turned into an exit with the reason."""

    def __getattr__(self, name: str):
        return getattr(Context.current(), name)

    @property
    def machines(self):
        return Context.current().trust.machines

    def fresh(self) -> Model:
        return Context.current().refresh()

    def act(self, needs: list[str]) -> Caller:
        try:
            return Context.current().act(needs)
        except Refused as e:
            raise fail(f"refused: {e}") from None

    def session(self, ref: str):
        """Context.session, with a refusal turned into an exit with the reason."""
        try:
            return Context.current().session(ref)
        except Refused as e:
            raise fail(str(e)) from None

    def staffer(self, ref: str):
        """Context.staffer, with a refusal turned into an exit with the reason."""
        try:
            return Context.current().staffer(ref)
        except Refused as e:
            raise fail(str(e)) from None


def refusing(fn):
    """Run fn, turning a refusal into an exit with the reason."""
    try:
        return fn()
    except Refused as e:
        raise fail(f"refused: {e}") from None


def _version(value: bool) -> None:
    """`--version`: what claudestra's plugin compares with the version it pins."""
    if value:
        print(importlib.metadata.version("claudestra"))
        raise typer.Exit(0)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    home: Annotated[
        Path | None, typer.Option(hidden=True, file_okay=False, help="A home folder other than ~ (tests).")
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option(
            hidden=True, file_okay=False, help="A config folder other than $XDG_CONFIG_HOME/claudestra (tests)."
        ),
    ] = None,
    version: Annotated[
        bool, typer.Option("--version", is_eager=True, callback=_version, help="Print claudestra's version and exit.")
    ] = False,
) -> None:
    c = Context(home, config)
    ctx.obj = Ctx()
    if c.restricted:
        # First, before any output, and on stderr so a command's --json stays clean.
        ui.err.print(Text(Context.RESTRICTED, style="bold yellow"))
        ui.err.print(Text(c.caller_line(), style="yellow"))
    if ctx.invoked_subcommand is None:
        if not ui.interactive():
            out.print(ctx.get_help())
            raise typer.Exit(0)
        menu(ctx)


def menu(ctx: typer.Context) -> None:
    """Every visible command, chosen by name; it then asks for what it needs."""
    group = ctx.command
    names = [n for n in group.list_commands(ctx) if not group.get_command(ctx, n).hidden]  # type: ignore[attr-defined]
    choices = [
        questionary.Choice(f"{n:<26} {group.get_command(ctx, n).get_short_help_str(60)}", value=n) for n in names
    ]  # type: ignore[attr-defined]
    choice = questionary.select(
        "claudestra", choices=choices, use_search_filter=True, use_jk_keys=False, instruction="(type to filter)"
    ).ask()
    if choice is None:
        raise typer.Exit(130)
    # Parsed as if typed with no arguments, so the command's own pickers ask for what it needs.
    cmd = group.get_command(ctx, choice)  # type: ignore[attr-defined]
    with cmd.make_context(choice, [], parent=ctx) as sub:
        cmd.invoke(sub)
