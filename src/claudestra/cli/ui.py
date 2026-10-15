"""What every command shares in front of the user: the consoles, how a refusal is shown, formatting, the
pickers and confirmation (only at a terminal), shell completion, and the options several commands
take."""

from __future__ import annotations

import datetime as dt
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import questionary
import typer
from rich.console import Console
from rich.text import Text

from ..caller import Refused
from ..model import SessionRecord
from ..ops import trash as trash_ops
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


def pick(message: str, choices: list[tuple[str, str]], what: str) -> str:
    """One value from (value, label) pairs, chosen at a terminal; otherwise the argument is required."""
    if not interactive():
        raise fail(f"give {what}; claudestra only asks at a terminal")
    if not choices:
        raise fail(f"there is no {what} to choose from")
    answer = questionary.select(
        message,
        choices=[questionary.Choice(text, value=v) for v, text in choices],
        use_search_filter=True,
        use_jk_keys=False,
        instruction="(type to filter)",
    ).ask()
    if answer is None:
        raise typer.Exit(130)
    return answer


def ask_text(message: str, what: str, default: str = "") -> str:
    if not interactive():
        raise fail(f"give {what}; claudestra only asks at a terminal")
    answer = questionary.text(message, default=default).ask()
    if answer is None:
        raise typer.Exit(130)
    return answer


def ask_folder(message: str, start: Path) -> Path:
    if not interactive():
        raise fail("give the folder; claudestra only asks at a terminal")
    answer = questionary.path(message, only_directories=True, default=str(start) + "/").ask()
    if answer is None:
        raise typer.Exit(130)
    return Path(answer)


def session_choices(
    sessions: list[SessionRecord], home: Path, keep: Callable[[SessionRecord], bool] = lambda _s: True
) -> list[tuple[str, str]]:
    rows = sorted((s for s in sessions if keep(s)), key=lambda s: -s.mtime)
    return [(s.session_id, f"{s.session_id[:8]}  {label(s)[:40]:<40}  {state(s):<12}  {where(s, home)}") for s in rows]


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


# --- completion ----------------------------------------------------------------------------------------


def _ctx():
    from .base import Ctx  # completion runs before any command, with its own context

    try:
        return Ctx(None, None)
    except Exception:  # noqa: BLE001 — completion must never break the shell
        return None


def complete_session(incomplete: str) -> list[tuple[str, str]]:
    if (c := _ctx()) is None:
        return []
    hits = []
    for s in sorted(c.model.sessions.values(), key=lambda x: -x.mtime):
        if s.session_id.startswith(incomplete) or (incomplete and label(s).lower().startswith(incomplete.lower())):
            hits.append((s.session_id, f"{label(s)}  {state(s)}"))
    return hits


def complete_staffer(incomplete: str) -> list[tuple[str, str]]:
    if (c := _ctx()) is None:
        return []
    return [
        (a.name, a.session[:8]) for a in c.trust.staff if a.folder and a.name.lower().startswith(incomplete.lower())
    ]


def complete_entry(incomplete: str) -> list[tuple[str, str]]:
    if (c := _ctx()) is None:
        return []
    return [
        (e.name, (mf or {}).get("title") or "") for e, mf in trash_ops.entries(c.fs) if e.name.startswith(incomplete)
    ]


def complete_host(incomplete: str) -> list[tuple[str, str]]:
    if (c := _ctx()) is None:
        return []
    return [
        (m.hostname, "accepts connections" if m.ssh else "")
        for m in c.machines.values()
        if m.hostname.lower().startswith(incomplete.lower()) and m.hostname.lower() != c.machine.hostname.lower()
    ]


# --- options several commands take -----------------------------------------------------------------------

Dry = Annotated[bool, typer.Option("--dry-run", "-n", help="Say what would happen, and do nothing.")]
Yes = Annotated[bool, typer.Option("--yes", "-y", help="Do not ask before changing anything.")]
Socket = Annotated[str | None, typer.Option(hidden=True, help="A tmux socket other than the default (tests).")]
AsJson = Annotated[bool, typer.Option("--json", help="Print JSON, for scripts.")]
SessionArg = Annotated[
    str | None,
    typer.Argument(
        help="Full ID, 8+ character prefix, bridge ID, job ID or name.",
        autocompletion=complete_session,
        show_default=False,
    ),
]
SessionsArg = Annotated[
    list[str] | None, typer.Argument(help="Sessions, as for one.", autocompletion=complete_session, show_default=False)
]
RunArg = Annotated[  # sessions to run in claudestra's tmux; staffers are offered first
    list[str] | None,
    typer.Argument(
        help="Staffer names, or any session's ID or 8+ character prefix.",
        autocompletion=complete_staffer,
        show_default=False,
    ),
]
HostArg = Annotated[
    str | None,
    typer.Argument(help="The other machine, as trust.yaml names it.", autocompletion=complete_host, show_default=False),
]
Force = Annotated[bool, typer.Option("--force", help="Stop a session even in the middle of a turn.")]
