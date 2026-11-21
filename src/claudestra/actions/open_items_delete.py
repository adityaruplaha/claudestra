"""`claudestra open-items delete`: remove an open item once its manager has checked the work is done. Its
manager's, or the user's; claudestra's log keeps what was removed."""

from __future__ import annotations

from ..caller import Refused
from ..context import Context
from ..ops import open_items as items_ops
from ..ops.common import log
from ..session import Session
from .base import SessionAction
from .permissions import SELF, USER, Relations


class OpenItemDelete(SessionAction):
    """On the manager that holds the item, found from the item's ULID."""

    verb = "open-items delete"
    who = Relations(frozenset({USER, SELF}))
    needs: list[str] = []
    reversible = True

    def __init__(self, ulid: str):
        owner, item = items_ops.find(Context.current().trust.config, ulid)
        super().__init__(Session(owner))
        self.ulid, self.title = item["id"], item.get("title", "")
        self.before: str | None = None

    def check(self) -> None:
        c = self.context
        if why := items_ops.owner_problem(c.trust, c.model.sessions, self.session.id):
            raise Refused(why)
        if not any(i["id"] == self.ulid for i in items_ops.read(c.trust.config, self.session.id)):
            raise Refused(f"{self.ulid} is no longer among the open items of {self.label!r}")

    def describe(self) -> list[str]:
        return [f"delete open item {self.ulid[-items_ops.SHORT :]} of {self.label!r}: {self.title}"]

    def run(self) -> None:
        c = self.context
        items = [i for i in items_ops.read(c.trust.config, self.session.id) if i["id"] != self.ulid]
        self.before = items_ops.write(c.trust.config, self.session.id, items)
        log(self.subject, "open-items delete", self.session.id, f"{self.ulid} {self.title!r}")

    def undo(self) -> None:
        items_ops.restore(self.context.trust.config, self.session.id, self.before)
