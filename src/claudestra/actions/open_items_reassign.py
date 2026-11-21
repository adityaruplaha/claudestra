"""`claudestra open-items reassign`: give an open item to another staffer on this machine. To a manager, it
moves to that manager's project, held by no one; to a specialist, to the project of the manager it answers to,
held by it. Only between managers on this machine, since each manager's file is written where it lives and the
other machine may take no connections: for one there, delete the item here and have its manager add it.
Its manager's, or the user's."""

from __future__ import annotations

from ..caller import Refused
from ..context import Context
from ..ops import open_items as items_ops
from ..ops.common import log
from ..session import Session
from .base import SessionAction
from .permissions import SELF, USER, Relations


class OpenItemReassign(SessionAction):
    """On the manager that holds the item now, found from the item's ULID."""

    verb = "open-items reassign"
    who = Relations(frozenset({USER, SELF}))
    needs: list[str] = []
    reversible = True

    def __init__(self, ulid: str, target: str):
        owner, item = items_ops.find(Context.current().trust.config, ulid)
        super().__init__(Session(owner))
        self.ulid, self.title, self.target = item["id"], item.get("title", ""), target
        self.to: str | None = None  # the manager it goes to
        self.held: str | None = None
        self.before: dict[str, str | None] = {}

    def check(self) -> None:
        c, t = self.context, self.context.trust
        if why := items_ops.owner_problem(t, c.model.sessions, self.session.id):
            raise Refused(why)
        if not any(i["id"] == self.ulid for i in items_ops.read(t.config, self.session.id)):
            raise Refused(f"{self.ulid} is no longer among the open items of {self.label!r}")
        sf = t.named(self.target) or t.staffer_now(self.target)
        if sf is None:
            raise Refused(f"{self.target!r} is not on the staff")
        if t.scope(sf.session) is not None:
            self.to, self.held = sf.session, None
        else:
            m = items_ops.manager_of(t, sf) if sf.folder is not None else None
            if m is None:
                raise Refused(f"{sf.name!r} answers to no manager on this machine, so no project here can hold it")
            self.to, self.held = m.session, sf.session
        if why := items_ops.owner_problem(t, c.model.sessions, self.to):
            raise Refused(f"{why}; delete the item here and have its manager add it there")

    def describe(self) -> list[str]:
        c = self.context
        to = c.name_of(self.to) or self.to
        held = f", held by {c.name_of(self.held)!r}" if self.held else ""
        return [f"reassign open item {self.ulid[-items_ops.SHORT :]} of {self.label!r} to {to!r}{held}: {self.title}"]

    def run(self) -> None:
        cfg = self.context.trust.config
        mine = items_ops.read(cfg, self.session.id)
        item = {**next(i for i in mine if i["id"] == self.ulid), "held_by": self.held}
        try:  # all or nothing: written to the new file first, then taken out of the old
            if self.to == self.session.id:
                self.before[self.to] = items_ops.write(
                    cfg, self.to, [item if i["id"] == self.ulid else i for i in mine]
                )
            else:
                self.before[self.to] = items_ops.write(cfg, self.to, [*items_ops.read(cfg, self.to), item])
                self.before[self.session.id] = items_ops.write(
                    cfg, self.session.id, [i for i in mine if i["id"] != self.ulid]
                )
        except Exception:
            self.undo()
            raise
        log(self.subject, "open-items reassign", self.session.id, f"{self.ulid} to {self.to}, held by {self.held}")

    def undo(self) -> None:
        for sid, before in self.before.items():
            items_ops.restore(self.context.trust.config, sid, before)
