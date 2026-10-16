"""The Typer app: the context every command gets, the preamble of every command that changes
something, and bare `claudestra`'s menu. The commands are in read.py, staff.py, sessions.py,
machines.py, setup.py and trust.py, which register themselves on `app` and the groups here."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import Annotated

import questionary
import typer
from rich.text import Text
from typer._completion_classes import completion_init

from ..actions.base import FS_CHECKS  # noqa: F401 - the commands import it from here
from ..caller import Caller, Refused
from ..context import Context
from ..model import Model
from . import ui
from .ui import fail, out

# Typer loads its shells' completion protocols only with its own --install-completion, which claudestra
# replaces with `install completion`; without them a shell asking for completions gets nothing.
completion_init()

app = typer.Typer(
    help="claudestra: run long-lived Claude Code sessions as a staff, with a chain of command (DESIGN.md). Bare `claudestra` at a terminal opens a menu.",
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
    pretty_exceptions_show_locals=False,
    add_completion=False,  # `claudestra install completion` installs it, for claudestra and clost
)


# The command groups, each registered here so that `--help` and the menu list them in this order. A bare
# group shows its help, as `-h` does.
def _group(name: str, help: str) -> typer.Typer:
    g = typer.Typer(
        help=help,
        rich_markup_mode="rich",
        no_args_is_help=True,
        context_settings={"help_option_names": ["-h", "--help"]},
    )
    app.add_typer(g, name=name)
    return g


session_app = _group("session", "Run, begin, rename and move sessions; `ls` lists them.")
staff_app = _group("staff", "List, hire, dismiss and describe staffers.")
trash_app = _group("trash", "List the trash, move sessions to it, restore and purge them.")
machine_app = _group("machine", "List the machines, and move sessions between them (moving is the user's alone).")
install_app = _group(
    "install",
    "Install claudestra's parts on this machine one at a time; `setup` walks through them all.",
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
        bool,
        typer.Option("--version", "-v", is_eager=True, callback=_version, help="Print claudestra's version and exit."),
    ] = False,
) -> None:
    c = Context(home, config)
    ctx.obj = Ctx()
    if c.restricted:
        # First, before any output, and on stderr so a command's --json stays clean.
        ui.err.print(Text(Context.RESTRICTED, style="bold yellow"))
        ui.err.print(Text(c.caller_line(), style="yellow"))
    if ui.interactive() and not c.restricted and not c.overridden:
        _remind(c)
    if ctx.invoked_subcommand is None:
        if not ui.interactive():
            out.print(ctx.get_help())
            raise typer.Exit(0)
        menu(ctx)


def _remind(c: Context) -> None:
    """At the user's terminal, a newer release, unless the user turned reminders off. Never in the way of a command."""
    from ..ops import preferences, updates

    try:
        if preferences.load(c.trust.config).get("update-reminders") == "no":
            return
        if note := updates.reminder(c.fs.home, importlib.metadata.version("claudestra")):
            ui.err.print(Text(note, style="dim"))
    except Exception:  # a reminder is never worth a failed command
        return


@app.command("help")
def help_(ctx: typer.Context) -> None:
    """Show this help, as -h does."""
    out.print(ctx.parent.get_help())


@app.command("version")
def version_() -> None:
    """Print claudestra's version, as -v does."""
    _version(True)


def _commands(ctx: typer.Context) -> dict[str, tuple]:
    """Every visible command by its full name, a group's as "group command": (its path of click commands)."""
    out: dict[str, tuple] = {}
    top = ctx.command
    for n in top.list_commands(ctx):  # type: ignore[attr-defined]
        cmd = top.get_command(ctx, n)  # type: ignore[attr-defined]
        if cmd.hidden or n in ("help", "version"):
            continue
        if hasattr(cmd, "list_commands"):
            for m in cmd.list_commands(ctx):
                sub = cmd.get_command(ctx, m)
                if not sub.hidden:
                    out[f"{n} {m}"] = ((n, cmd), (m, sub))
        else:
            out[n] = ((n, cmd),)
    return out


def menu(ctx: typer.Context) -> None:
    """Every visible command, a group's by its full name, chosen by name; it then asks for what it needs."""
    commands = _commands(ctx)
    choices = [
        questionary.Choice(f"{n:<26} {path[-1][1].get_short_help_str(60)}", value=n) for n, path in commands.items()
    ]
    choice = questionary.select(
        "claudestra", choices=choices, use_search_filter=True, use_jk_keys=False, instruction="(type to filter)"
    ).ask()
    if choice is None:
        raise typer.Exit(130)
    # Parsed as if typed with no arguments, so the command's own pickers ask for what it needs.
    # A group itself is not parsed, since a bare group shows its help.
    cmd = commands[choice][-1][1]
    with cmd.make_context(choice, [], parent=ctx) as sub:
        cmd.invoke(sub)
