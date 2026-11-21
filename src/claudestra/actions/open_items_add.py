"""`claudestra open-items add`: a manager adds an open item to its project. Its own, or the user's for it."""

from __future__ import annotations

from ..caller import Refused
from ..ops import open_items as items_ops
from ..ops.common import log
from .base import SessionAction
from .permissions import SELF, USER, Relations


class OpenItemAdd(SessionAction):
    """On the manager that holds the item (a claudestra.session.Session)."""

    verb = "open-items add"
    who = Relations(frozenset({USER, SELF}))
    needs: list[str] = []
    reversible = True

    def __init__(self, owner, fields: dict):
        super().__init__(owner)
        self.fields = fields
        self.item: dict | None = None
        self.before: str | None = None

    def check(self) -> None:
        c = self.context
        if why := items_ops.owner_problem(c.trust, c.model.sessions, self.session.id):
            raise Refused(why)
        f = self.fields
        title = (f.get("title") or "").strip()
        if not title:
            raise Refused("an open item needs a title")
        state = f.get("state") or "open"
        if state not in items_ops.STATES:
            raise Refused(f"state is one of {', '.join(items_ops.STATES)}")
        held = f.get("held_by")
        if held:
            sf = c.trust.named(held) or c.trust.staffer_now(held)
            if sf is None or not items_ops.in_project(c.trust, self.session.id, sf.session):
                raise Refused(f"{held!r} is not a specialist in the project of {self.label!r}")
            held = sf.session
        self.item = {
            "id": self.item["id"] if self.item else items_ops.new_id(),
            "title": title,
            "description": (f.get("description") or "").strip(),
            "state": state,
            "waiting_on": items_ops.resolve_wait(c.trust, f.get("waiting_on")),
            "held_by": held or None,
            "where": (f.get("where") or "").strip(),
        }

    def describe(self) -> list[str]:
        return [f"add to the open items of {self.label!r}: {self.item['id'][-items_ops.SHORT :]} {self.item['title']}"]

    def run(self) -> str:
        c = self.context
        items = items_ops.read(c.trust.config, self.session.id)
        self.before = items_ops.write(c.trust.config, self.session.id, [*items, self.item])
        log(self.subject, "open-items add", self.session.id, f"{self.item['id']} {self.item['title']!r}")
        return self.item["id"]

    def undo(self) -> None:
        items_ops.restore(self.context.trust.config, self.session.id, self.before)
