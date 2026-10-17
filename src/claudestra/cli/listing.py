"""How the commands that list things print them: a table at a terminal, or JSON with --json, from the same rows.
A command declares a `Listing` (its columns, and the record each row becomes in JSON) and hands it the rows;
the cells that recur across lists (a session's ID, a scope, a machine, a staffer's tags) are made here, so that
they read and are coloured the same in every list, and in the pickers `select` shows, which use the same
cells. No list command builds a table of its own."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from rich.table import Table
from rich.text import Text

from .ui import out

Cell = str | Text


@dataclass
class Column[R]:
    """One column: its header, the cell a row gives it, and the column's own style."""

    header: str
    cell: Callable[[R], Cell]
    style: str = ""
    wrap: bool = False  # only the last, longest columns wrap; the rest keep to one line


@dataclass
class Listing[R]:
    """A list one command prints: `columns` at a terminal, and `record` for each row with --json."""

    columns: list[Column[R]]
    record: Callable[[R], dict[str, Any]]
    title: str | None = None
    empty: str | None = None  # said, in place of an empty table, when there are no rows

    def print(
        self, rows: Iterable[R], as_json: bool = False, more: Iterable[tuple[tuple[Cell, ...], dict]] = ()
    ) -> None:
        """Print the rows. `more` are rows of another kind, each as its cells and its JSON record, made by the
        command (as for runs with no transcript yet), printed after the rest."""
        rows, more = list(rows), list(more)
        if as_json:
            print(json.dumps([self.record(r) for r in rows] + [rec for _, rec in more], indent=2))
            return
        if not rows and not more and self.empty:
            out.print(Text(self.empty, style="green"))
            return
        t = Table(title=self.title, title_justify="left", box=None, header_style="bold", pad_edge=False)
        for col in self.columns:
            t.add_column(col.header, style=col.style or None, no_wrap=not col.wrap)
        for r in rows:
            t.add_row(*(col.cell(r) for col in self.columns))
        for cells, _ in more:
            t.add_row(*cells)
        out.print(t)


# --- the cells that recur ------------------------------------------------------------------------------


def short_id(sid: str) -> Text:
    return Text(sid[:8], style="cyan")


def name(text: str | None) -> Text:
    return Text(text or "-", style="bold")


def scope(sc: str | None) -> Text:
    """A scope: a device scope stands out more than a folder one; a specialist has none."""
    return Text(sc or "-", style={"device": "bold magenta", "folder": "magenta"}.get(sc or "", "dim"))


def machine(host: str, here: str) -> Text:
    """A machine's name: this one in green, another in blue."""
    return Text(host, style="green" if host.lower() == here.lower() else "blue")


def machines(hosts: list[str], here: str) -> Text:
    if not hosts:
        return Text("-", style="dim")
    t = Text()
    for i, h in enumerate(hosts):
        t.append(" or " if i else "", style="dim")
        t.append_text(machine(h, here))
    return t


def dim(text: str | None) -> Text:
    return Text(text or "-", style="dim")


def tags(c, sid: str, s=None) -> Text:
    """What else is true of a session: its scope, whether it starts at login, is protected, is on the staff."""
    t = Text()
    sc = c.trust.scope(sid)
    for text, style in (
        (f"{sc} scope" if sc else None, "magenta"),
        ("autostart" if sid in c.trust.autostart(c.machine.hostname) else None, "blue"),
        ("protected" if s and c.trust.is_protected(s.folder, s.homes[0]) else None, "yellow"),
        ("staff" if c.trust.staff_file(sid) else None, "cyan"),
    ):
        if text:
            t.append(("  " if t else "") + text, style=style)
    return t


# --- the same rows, for a picker ------------------------------------------------------------------------


def _ptk_style(style) -> str:
    """A rich style as prompt_toolkit writes it, for the few styles the lists use."""
    if style is None:
        return ""
    parts = ["bold"] if style.bold else []
    if style.dim:
        parts.append("fg:ansibrightblack")
    elif style.color is not None and style.color.name:
        parts.append("fg:ansi" + style.color.name.replace("_", ""))
    return " ".join(parts)


def _tokens(cell: Cell, width: int) -> list[tuple[str, str]]:
    """One cell as prompt_toolkit tokens, padded to `width`: each run of characters with one style."""
    from rich.console import Console

    t = (cell if isinstance(cell, Text) else Text(cell)).copy()
    t.truncate(width, pad=True)
    console = Console(color_system="standard")
    tokens: list[tuple[str, str]] = []
    for i, ch in enumerate(t.plain):
        style = _ptk_style(t.get_style_at_offset(console, i))
        if tokens and tokens[-1][0] == style:
            tokens[-1] = (style, tokens[-1][1] + ch)
        else:
            tokens.append((style, ch))
    return tokens


def _len(cell: Cell) -> int:
    return cell.cell_len if isinstance(cell, Text) else Text(cell).cell_len


def aligned(headers: tuple[str, ...], rows: list[tuple[Cell, ...]]) -> tuple[str, list[list[tuple[str, str]]]]:
    """A picker's rows as a table: the header line, and each row as prompt_toolkit tokens, in columns as wide as
    their widest cell, coloured as the lists colour them. The last column is not padded."""
    n = max([len(headers), *(len(r) for r in rows)])
    widths = [
        max([len(headers[i]) if i < len(headers) else 0, *(_len(r[i]) for r in rows if i < len(r))]) for i in range(n)
    ]
    lines = []
    for r in rows:
        toks: list[tuple[str, str]] = []
        for i, cell in enumerate(r):
            toks += ([("", "  ")] if i else []) + _tokens(cell, widths[i] if i < len(r) - 1 else _len(cell))
        lines.append(toks)
    header = "  ".join(h.ljust(w) for h, w in zip(headers, widths, strict=False)).rstrip()
    return header, lines


def plain(cells: tuple[Cell, ...]) -> str:
    """A row as plain text, for shell completion."""
    return "  ".join(c.plain if isinstance(c, Text) else c for c in cells)


# --- staffers ---------------------------------------------------------------------------------------------


def lives_on(c, sf) -> list[str]:
    """The machine a staffer lives on: this one, if its transcript is here; else the others its staff file names."""
    if sf.session in c.model.sessions:
        return [c.machine.hostname]
    return [str(h) for h in sf.folders if str(h).lower() != c.machine.hostname.lower()]


def staff_folder(c, sf) -> Cell:
    """A staffer's folder here; for one with none here that lives on one other machine, its folder there, dimmed,
    as its staff file writes it (~ is that machine's home)."""
    from ..trust import tilde

    if sf.folder is not None:
        return tilde(sf.folder, c.fs.home)
    on = lives_on(c, sf)
    there = [f for h, f in sf.folders.items() if len(on) == 1 and str(h) == on[0]]
    return dim(there[0] if there else None)
