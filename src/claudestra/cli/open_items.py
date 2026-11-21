"""`claudestra open-items`: a manager's open items. Reading them is anyone's; a manager changes its own, and the
user anyone's (actions/open_items_*.py)."""

from __future__ import annotations

import datetime as _dt
from typing import Annotated

import typer
from rich.text import Text

from ..actions.open_items_add import OpenItemAdd
from ..actions.open_items_delete import OpenItemDelete
from ..actions.open_items_get import OpenItemGet
from ..actions.open_items_list import OpenItemsList
from ..actions.open_items_reassign import OpenItemReassign
from ..actions.open_items_search import OpenItemsSearch
from ..actions.open_items_update import OpenItemUpdate
from ..ops import open_items as items_ops
from ..session import Session
from . import listing, select
from .base import Ctx, open_items_app, refusing
from .ui import AsJson, Dry, Yes, go_ahead, out

ITEM = select.OpenItems()
PROJECT = select.Projects()
MANAGER = select.Staffers(scoped=True, message="Whose project?", help="The manager it goes to; picked at a terminal.")
TARGET = select.Staffers(message="To whom?", help="A manager, or a specialist; picked at a terminal.")
TITLE = select.Text("Title:", "a title")

All = Annotated[bool, typer.Option("--all", help="Every manager's open items, on every machine.")]
State = Annotated[str | None, typer.Option("--state", help="open, waiting or blocked.")]
WaitingOn = Annotated[str | None, typer.Option("--waiting-on", help="user, upstream, a staffer's name, or none.")]
Where = Annotated[str | None, typer.Option("--where", help="Where the project tracks it in detail.")]
Description = Annotated[str | None, typer.Option("--description", help="A short description.")]


def _rows(c, found: list[tuple[str, dict]], as_json: bool, owners: bool, empty: str) -> None:
    columns = [listing.Column("item", lambda p: listing.item_id(p[1]["id"]))]
    if owners:
        columns.append(listing.Column("manager", lambda p: listing.staffer_name(c, p[0])))
    columns += [
        listing.Column("title", lambda p: p[1].get("title", "")),
        listing.Column("state", lambda p: listing.item_state(p[1])),
        listing.Column("waiting on", lambda p: _wait(c, p[1].get("waiting_on"))),
        listing.Column("held by", lambda p: listing.staffer_name(c, p[1].get("held_by"))),
        listing.Column("where", lambda p: listing.dim(p[1].get("where")), wrap=True),
    ]
    listing.Listing(columns, lambda p: {"manager": p[0], **p[1]}, empty=empty).print(found, as_json)


def _wait(c, value: str | None) -> Text:
    return Text(value, style="magenta") if value in items_ops.WAITS else listing.staffer_name(c, value)


def _whose(c: Ctx, session: str | None, everything: bool) -> tuple[str | None, bool]:
    """The staffer given, or the caller's own project; the user, giving none at a terminal, picks one or all."""
    if everything or session is not None:
        return (None if everything else PROJECT.get(session)), everything or session == "all"
    if c.subject.kind == "human":
        picked = PROJECT.get(None)
        return (None, True) if picked == "all" else (picked, False)
    return None, False


@open_items_app.command("list")
def list_(
    ctx: typer.Context,
    session: PROJECT.arg = None,
    everything: All = False,
    waiting_on: WaitingOn = None,
    as_json: AsJson = False,
) -> None:
    """The open items of a project: a manager's own, or those a specialist holds; with none, the caller's; --all for every manager's."""
    c: Ctx = ctx.obj
    sid, everything = _whose(c, session, everything)
    found = refusing(lambda: OpenItemsList(sid, everything, waiting_on).perform())
    _rows(c, found, as_json, owners=everything or c.subject.kind == "human", empty="no open items")


@open_items_app.command()
def search(
    ctx: typer.Context,
    text: Annotated[str, typer.Argument(help="Text in the title, description or where, in any case.")],
    session: PROJECT.arg = None,
    everything: All = False,
    as_json: AsJson = False,
) -> None:
    """The open items in a project whose title, description or where holds the text; --all for every manager's."""
    c: Ctx = ctx.obj
    sid, everything = _whose(c, session, everything)
    found = refusing(lambda: OpenItemsSearch(text, sid, everything).perform())
    _rows(c, found, as_json, owners=True, empty=f"no open item holds {text!r}")


@open_items_app.command()
def get(ctx: typer.Context, item: ITEM.arg = None, as_json: AsJson = False) -> None:
    """One open item in full: its manager, when it was made, and every field."""
    c: Ctx = ctx.obj
    owner, i = refusing(lambda: OpenItemGet(ITEM.get(item)).perform())
    made = _dt.datetime.fromtimestamp(items_ops.made_at(i["id"])).astimezone().isoformat(timespec="seconds")
    if as_json:
        import json

        out.print_json(json.dumps({"manager": owner, "made": made, **i}))
        return
    rows = [
        ("item", i["id"]),
        ("manager", listing.staffer_name(c, owner)),
        ("made", made),
        ("title", i.get("title", "")),
        ("description", i.get("description") or "-"),
        ("state", listing.item_state(i)),
        ("waiting on", _wait(c, i.get("waiting_on"))),
        ("held by", listing.staffer_name(c, i.get("held_by"))),
        ("where", i.get("where") or "-"),
    ]
    for k, v in rows:
        out.print(Text(f"{k:<12}", style="bold") + (v if isinstance(v, Text) else Text(str(v))))


@open_items_app.command()
def add(
    ctx: typer.Context,
    title: Annotated[str | None, typer.Argument(help="What is open, in a line; asked for at a terminal.")] = None,
    manager: Annotated[
        str | None, typer.Option("--manager", help="The manager whose project it is; the caller, for a manager.")
    ] = None,
    description: Description = None,
    state: State = None,
    waiting_on: WaitingOn = None,
    held_by: Annotated[str | None, typer.Option("--held-by", help="The specialist in the project holding it.")] = None,
    where: Where = None,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Add an open item to a manager's project (the manager's own, or the user's)."""
    c: Ctx = ctx.obj
    owner = MANAGER.get(manager) if manager or c.subject.session is None else c.subject.session
    fields = {
        "title": TITLE.get(title),
        "description": description,
        "state": state,
        "waiting_on": waiting_on,
        "held_by": held_by,
        "where": where,
    }
    ulid = refusing(lambda: OpenItemAdd(Session(owner), fields).perform(go_ahead(yes, dry)))
    if ulid:
        out.print(Text(f"added {ulid}", style="green"))


@open_items_app.command()
def update(
    ctx: typer.Context,
    item: ITEM.arg = None,
    title: Annotated[str | None, typer.Option("--title", help="A new title.")] = None,
    description: Description = None,
    state: State = None,
    waiting_on: WaitingOn = None,
    where: Where = None,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Change an open item's title, description, state, what it waits on, or where it is tracked (its manager's, or the user's)."""
    changes = {"title": title, "description": description, "state": state, "waiting_on": waiting_on, "where": where}
    refusing(lambda: OpenItemUpdate(ITEM.get(item), changes).perform(go_ahead(yes, dry)))


@open_items_app.command()
def delete(ctx: typer.Context, item: ITEM.arg = None, dry: Dry = False, yes: Yes = False) -> None:
    """Delete an open item once its manager has checked the work is done (its manager's, or the user's)."""
    refusing(lambda: OpenItemDelete(ITEM.get(item)).perform(go_ahead(yes, dry)))


@open_items_app.command()
def reassign(
    ctx: typer.Context, item: ITEM.arg = None, to: TARGET.arg = None, dry: Dry = False, yes: Yes = False
) -> None:
    """Give an open item to a manager on this machine, or to a specialist, held by it in its manager's project (its manager's, or the user's)."""
    refusing(lambda: OpenItemReassign(ITEM.get(item), TARGET.get(to)).perform(go_ahead(yes, dry)))
