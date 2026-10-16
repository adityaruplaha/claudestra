"""What a command acts on, selected one way everywhere (DESIGN.md §10).

A selector is declared once for a kind of argument, with what the command allows (`Sessions(staff=False,
running=False)`, `Staffers(scoped=True)`), and gives three things from those same restrictions, so they
never disagree: the command-line argument with its help and shell completion (`.arg`), the list a person
picks from at a terminal, and the value a token names (`.get`). Given on the command line, a value is used
as given; left out at a terminal, it is picked from the list; left out with no terminal, which is how a
session runs claudestra, the command refuses and names what to give. `.where(...)` narrows a selector
further with what is only known as the command runs, such as the machine a staffer must work on.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import questionary
import typer

from ..caller import Refused
from ..claude_fs import UUID
from ..ops import trash as trash_ops
from . import ui
from .ui import fail, label, state, where


def _need(what: str) -> None:
    if not ui.interactive():
        raise fail(f"give {what}; claudestra picks it from a list only at a terminal")


def _context():
    """The process's context; completion runs before any command, so it makes its own."""
    from ..context import Context

    return Context._current or Context(None, None)


def pick(message: str, choices: list[tuple[str, str]], what: str) -> str:
    """One value from (value, label) pairs, picked at a terminal from a list that filters as one types."""
    _need(what)
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


def pick_many(message: str, choices: list[tuple[str, str]], what: str) -> list[str]:
    """Any number of values, at least one, ticked at a terminal in a list that filters as one types."""
    _need(what)
    if not choices:
        raise fail(f"there is no {what} to choose from")
    answer = questionary.checkbox(
        message,
        choices=[questionary.Choice(text, value=v) for v, text in choices],
        use_search_filter=True,
        use_jk_keys=False,
        instruction="(type to filter, space ticks, enter goes on)",
    ).ask()
    if not answer:
        raise typer.Exit(130)
    return answer


class Selector:
    """One kind of argument. A subclass says what can be chosen (`choices`) and what a token names (`resolve`)."""

    what = "a value"  # what to give, as a refusal names it
    message = "Which?"
    help = ""

    def __init__(self, *, many: bool = False, message: str | None = None, help: str | None = None):
        self.many = many
        self.message = message or self.message
        self.help = help or self.help

    def where(self, **narrower) -> Selector:
        """A copy narrowed further, with what is only known as the command runs."""
        other = copy.copy(self)
        for k, v in narrower.items():
            setattr(other, k, v)
        return other

    def choices(self) -> list[tuple[str, str]]:
        """(value, label) for each value this selector allows, in the order a person should see them."""
        raise NotImplementedError

    def resolve(self, token: str) -> Any:
        return token

    def get(self, token: Any = None) -> Any:
        """The value a token names; left out, picked at a terminal. A list for a selector of many."""
        if self.many:
            tokens = list(token or []) or pick_many(self.message, self.choices(), self.what)
            return [self.resolve(t) for t in tokens]
        return self.resolve(token if token is not None else pick(self.message, self.choices(), self.what))

    def complete(self, incomplete: str) -> list[tuple[str, str]]:
        """Shell completion: the allowed values that start with what is typed, or whose label does."""
        try:
            low = incomplete.lower()
            return [(v, t) for v, t in self.choices() if v.startswith(incomplete) or (low and low in t.lower())]
        except Exception:  # noqa: BLE001 - completion must never break the shell
            return []

    @property
    def arg(self) -> Any:
        """The Typer argument: optional, with this selector's help and completion."""
        kind = list[str] | None if self.many else str | None
        return Annotated[
            kind, typer.Argument(help=self.help, autocompletion=self.complete, show_default=False, metavar=None)
        ]


def _resolve_session(token: str):
    try:
        return _context().session(token)
    except Refused as e:
        raise fail(str(e)) from None


class Sessions(Selector):
    """Sessions on this machine: on the staff or not (`staff`), running or stopped (`running`), filed here (`here`),
    and passing `keep`. Staffers are listed first, then by last activity."""

    what = "a session"
    message = "Which session?"
    help = "A full ID, 8+ character prefix, bridge or job ID, title or staffer's name; picked at a terminal."

    def __init__(
        self,
        *,
        staff: bool | None = None,
        running: bool | None = None,
        here: bool | None = None,
        keep: Callable = lambda _s: True,
        **kw,
    ):
        super().__init__(**kw)
        self.staff, self.running, self.here, self.keep = staff, running, here, keep

    def allows(self, s) -> bool:
        return (
            (self.staff is None or bool(s.staff_file) == self.staff)
            and (self.running is None or bool(s.runs) == self.running)
            and (self.here is None or bool(s.homes) == self.here)
            and self.keep(s)
        )

    def choices(self) -> list[tuple[str, str]]:
        c = _context()
        found = sorted(
            (s for s in c.model.sessions.values() if self.allows(s)), key=lambda s: (not s.staff_file, -s.mtime)
        )
        return [
            (s.session_id, f"{s.session_id[:8]}  {label(s)[:40]:<40}  {state(s):<12}  {where(s, c.fs.home)}")
            for s in found
        ]

    def resolve(self, token: str):
        return _resolve_session(token)


class Staffers(Selector):
    """Staffers, as their session IDs: with a folder on this machine (`here`) or on machine `on`, with a scope or
    without (`scoped`), and passing `keep`."""

    what = "a staffer"
    message = "Which staffer?"
    help = "A staffer's name or full ID, or anything that names its session here; picked at a terminal."

    def __init__(
        self,
        *,
        here: bool | None = None,
        on: str | None = None,
        scoped: bool | None = None,
        keep: Callable[[str], bool] = lambda _sid: True,
        **kw,
    ):
        super().__init__(**kw)
        self.here, self.on, self.scoped, self.keep = here, on, scoped, keep

    def choices(self) -> list[tuple[str, str]]:
        c = _context()
        t = c.trust

        def allowed(sf) -> bool:
            return (
                (self.here is None or (sf.folder is not None) == self.here)
                and (self.on is None or any(h.lower() == self.on.lower() for h in sf.folders))
                and (self.scoped is None or (t.scope(sf.session) is not None) == self.scoped)
                and self.keep(sf.session)
            )

        return [
            (
                sf.session,
                f"{sf.name}  ({sf.session[:8]}" + (f", {t.scope(sf.session)} scope)" if t.scope(sf.session) else ")"),
            )
            for sf in sorted(t.staff, key=lambda f: f.name)
            if allowed(sf)
        ]

    def complete(self, incomplete: str) -> list[tuple[str, str]]:
        """Completed by name, which is what a person types."""
        try:
            t = _context().trust
            ids = dict(self.choices())
            return [(sf.name, sf.session[:8]) for sf in t.staff if sf.session in ids and sf.name.startswith(incomplete)]
        except Exception:  # noqa: BLE001
            return []

    def resolve(self, token: str) -> str:
        if UUID.match(token):
            return token
        named = _context().trust.named(token)
        return named.session if named else _resolve_session(token).id


class TrashEntries(Selector):
    what = "a trash entry"
    message = "Which trash entry?"
    help = "A trash entry, or 8+ characters of its session ID; picked at a terminal."

    def choices(self) -> list[tuple[str, str]]:
        return [(e.name, f"{e.name}  {mf.get('title') or '-'}") for e, mf in trash_ops.entries(_context().fs) if mf]


class Machines(Selector):
    """Machines trust.yaml describes; another one only, if `other`."""

    what = "a machine"
    message = "Which machine?"
    help = "A machine, as trust.yaml names it; picked at a terminal."

    def __init__(self, *, other: bool = True, **kw):
        super().__init__(**kw)
        self.other = other

    def choices(self) -> list[tuple[str, str]]:
        c = _context()
        here = c.machine.hostname.lower()
        return [
            (m.hostname, m.hostname + ("  (accepts connections)" if m.ssh else ""))
            for m in c.trust.machines.values()
            if not (self.other and m.hostname.lower() == here)
        ]


class OneOf(Selector):
    """One of a fixed set of values, each with what it means."""

    def __init__(self, options: dict[str, str], what: str, message: str, **kw):
        super().__init__(message=message, help=kw.pop("help", None) or f"One of {', '.join(options)}.", **kw)
        self.options, self.what = options, what

    def choices(self) -> list[tuple[str, str]]:
        return [(k, f"{k}: {v}" if v else k) for k, v in self.options.items()]

    def resolve(self, token: str) -> str:
        if token not in self.options:
            raise fail(f"refused: {self.what} is one of {', '.join(self.options)}, not {token!r}")
        return token


class Folder(Selector):
    """A folder on this machine, made absolute; browsed to at a terminal. The shell completes paths itself."""

    what = "the folder"
    message = "Which folder?"
    help = "A folder; browsed to at a terminal."

    def get(self, token: Path | str | None = None, start: Path | None = None) -> Path:
        if token is None:
            _need(self.what)
            home = start or _context().fs.home
            answer = questionary.path(self.message, only_directories=True, default=str(home) + "/").ask()
            if answer is None:
                raise typer.Exit(130)
            token = answer
        return Path(token).expanduser().absolute()

    @property
    def arg(self) -> Any:
        return Annotated[Path | None, typer.Argument(help=self.help, file_okay=False, show_default=False)]


class Text(Selector):
    """Free text, typed at a terminal, with a default to edit."""

    def __init__(self, message: str, what: str, default: str = "", **kw):
        super().__init__(message=message, **kw)
        self.what, self.default = what, default

    def get(self, token: str | None = None, default: str | None = None) -> str:
        if token is not None:
            return token
        _need(self.what)
        answer = questionary.text(self.message, default=self.default if default is None else default).ask()
        if answer is None:
            raise typer.Exit(130)
        return answer


class Windows(Selector):
    """The sessions running in claudestra's tmux, by their windows, and `all` for the whole tmux session."""

    what = "a session, or all"
    message = "Which session's window?"
    help = "The session whose window to open, or `all` for the whole tmux session; picked at a terminal."

    def __init__(self, *, socket: str | None = None, **kw):
        super().__init__(**kw)
        self.socket = socket

    def choices(self) -> list[tuple[str, str]]:
        from ..runners import tmux as runner

        c = _context()
        rows = [("all", "all: the whole tmux session")]
        windows = runner.Tmux(self.socket).windows()
        return rows + [(w.session, f"{w.session[:8]}  {c.name_of(w.session) or w.name}") for w in windows if not w.dead]

    def resolve(self, token: str) -> str | None:
        """The session's ID, or None for the whole tmux session."""
        return None if token == "all" else _resolve_session(token).id
