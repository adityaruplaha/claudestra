"""What every command shares in front of the user: the consoles, how a refusal is shown, formatting, the
pickers and confirmation (only at a terminal), shell completion, and the options several commands
take."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Annotated

import questionary
import typer
from rich.console import Console
from rich.text import Text

from ..caller import Refused
from ..model import SessionRecord
from ..trust import tilde

_tty = sys.stdout.isatty()
# Colour drops itself off a terminal or under NO_COLOR. Off a terminal nothing wraps either, since
# Claude sessions read this output. Markup is off: names such as "[my-stack] manager" would
# otherwise be read as style tags.
out = Console(highlight=False, markup=False, soft_wrap=not _tty, width=None if _tty else 10_000)
err = Console(stderr=True, highlight=False, markup=False, soft_wrap=True)


def interactive() -> bool:
    """A person at a terminal. A Claude session's commands have none, so Claude sessions are never prompted."""
    return sys.stdin.isatty() and sys.stdout.isatty()


def fail(msg: str, code: int = 1) -> typer.Exit:
    err.print(Text(msg, style="bold red"))
    return typer.Exit(code)


def refused(e: Refused) -> typer.Exit:
    return fail(f"refused: {e}")


# --- formatting -----------------------------------------------------------------------------------


def when(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def state(s: SessionRecord) -> str:
    return s.state


def state_text(s: SessionRecord) -> Text:
    if not s.runs:
        return Text(state(s), style="dim")
    return Text(state(s), style="bold yellow" if any(r.status == "busy" for r in s.runs) else "green")


def where(s: SessionRecord, home: Path) -> str:
    return tilde(s.folder, home) if s.folder else f"slug {', '.join(s.homes)}"


def label(s: SessionRecord) -> str:
    return (s.staff_file.name if s.staff_file else s.name) or "-"


def outcome(line: str) -> Text:
    """A runner's one-line report, coloured by its first word."""
    word = line.split(maxsplit=1)[0] if line.strip() else ""
    colours = {"started": "green", "stopped": "green", "running": "cyan", "cleared": "yellow", "exited": "yellow"}
    return Text(line, style=colours.get(word, "dim" if word.startswith("would") or word == "not" else ""))


def lines(items: list[str], style: str = "") -> None:
    for line in items:
        out.print(Text(line, style=style))


# --- pickers and confirmation -------------------------------------------------------------------------


def confirmed(yes: bool, dry: bool, prompt: str = "Go ahead?") -> None:
    """At a terminal, a change is confirmed first; -y, a dry run, or no terminal skip the question.

    It is asked before claudestra takes its lock, so a question left open never holds up another claudestra.
    """
    if yes or dry or not interactive():
        return
    if not questionary.confirm(prompt, default=False).ask():
        raise fail("nothing changed")


def go_ahead(yes: bool, dry: bool, show=None, prompt: str = "Go ahead?"):
    """An action's go_ahead (actions/base.py): print its plan, stop there for a dry run, and ask at a
    terminal. `show` turns a plan line into what is printed."""

    def decide(plan: list[str]) -> bool:
        for line in plan:
            out.print(show(line) if show else Text(line))
        if dry:
            out.print(Text("dry run; nothing changed", style="dim"))
            return False
        confirmed(yes, dry, prompt)
        return True

    return decide


# --- options several commands take -----------------------------------------------------------------------

Dry = Annotated[bool, typer.Option("--dry-run", "-n", help="Say what would happen, and do nothing.")]
Yes = Annotated[bool, typer.Option("--yes", "-y", help="Do not ask before changing anything.")]
Socket = Annotated[str | None, typer.Option(hidden=True, help="A tmux socket other than the default (tests).")]
AsJson = Annotated[bool, typer.Option("--json", help="Print JSON, for scripts.")]
CopyMemory = Annotated[
    bool,
    typer.Option(
        "--copy-memory",
        help="Also copy the project's auto-memory, adding what the destination lacks, overwriting nothing.",
    ),
]
Force = Annotated[bool, typer.Option("--force", help="Stop a session even in the middle of a turn.")]
