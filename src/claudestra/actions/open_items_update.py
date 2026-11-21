"""`claudestra open-items update`: change an open item's title, description, state, what it waits on or where it
is tracked. Its manager's, or the user's; a specialist reports to its manager instead."""

from __future__ import annotations

from ..caller import Refused
from ..context import Context
from ..ops import open_items as items_ops
from ..ops.common import log
from ..session import Session
from .base import SessionAction
from .permissions import SELF, USER, Relations

CHANGEABLE = ("title", "description", "state", "waiting_on", "where")


class OpenItemUpdate(SessionAction):
    """On the manager that holds the item, found from the item's ULID."""

    verb = "open-items update"
    who = Relations(frozenset({USER, SELF}))
    needs: list[str] = []
    reversible = True

    def __init__(self, ulid: str, changes: dict):
        owner, item = items_ops.find(Context.current().trust.config, ulid)
        super().__init__(Session(owner))
        self.ulid, self.changes = item["id"], {k: v for k, v in changes.items() if v is not None}
        self.before: str | None = None
        self.new: dict | None = None

    def check(self) -> None:
        c = self.context
        if why := items_ops.owner_problem(c.trust, c.model.sessions, self.session.id):
            raise Refused(why)
        if not self.changes:
            raise Refused(f"say what changes: {', '.join('--' + k.replace('_', '-') for k in CHANGEABLE)}")
        item = next((i for i in items_ops.read(c.trust.config, self.session.id) if i["id"] == self.ulid), None)
        if item is None:
            raise Refused(f"{self.ulid} is no longer among the open items of {self.label!r}")
        new = dict(item)
        for k, v in self.changes.items():
            v = v.strip() if isinstance(v, str) else v
            if k == "title" and not v:
                raise Refused("an open item needs a title")
            if k == "state" and v not in items_ops.STATES:
                raise Refused(f"state is one of {', '.join(items_ops.STATES)}")
            new[k] = items_ops.resolve_wait(c.trust, v) if k == "waiting_on" else v
        self.new = new

    def describe(self) -> list[str]:
        what = ", ".join(f"{k} {self.new.get(k) or '-'}" for k in self.changes)
        return [f"update open item {self.ulid[-items_ops.SHORT :]} of {self.label!r}: {what}"]

    def run(self) -> None:
        c = self.context
        items = [self.new if i["id"] == self.ulid else i for i in items_ops.read(c.trust.config, self.session.id)]
        self.before = items_ops.write(c.trust.config, self.session.id, items)
        log(self.subject, "open-items update", self.session.id, f"{self.ulid} {', '.join(self.changes)}")

    def undo(self) -> None:
        items_ops.restore(self.context.trust.config, self.session.id, self.before)
