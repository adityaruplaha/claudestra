"""`claudestra open-items list`: the open items of a project. A manager's own; a specialist's, those it holds;
with no session, the caller's (its own if a manager, those it holds if a specialist); every manager's with
`all`. Reading, so anyone's."""

from __future__ import annotations

from ..caller import Refused
from ..ops import open_items as items_ops
from .base import ReadOnlyAction


class OpenItemsList(ReadOnlyAction):
    verb = "open-items list"

    def __init__(self, session: str | None = None, everything: bool = False, waiting_on: str | None = None):
        super().__init__(session)
        self.everything, self.waiting_on = everything, waiting_on

    def whose(self) -> str | None:
        """The session whose items these are: the one given, or the caller; None for every manager's."""
        if self.everything:
            return None
        sid = self.object or self.subject.session
        if sid is None:
            raise Refused("the user has no project of their own; name a manager or a specialist, or ask for all")
        return sid

    def run(self) -> list[tuple[str, dict]]:
        c, t = self.context, self.context.trust
        sid = self.whose()
        found = [(owner, i) for owner, items in items_ops.every(t.config).items() for i in items]
        if sid is not None:
            sf = t.staffer_now(sid)
            if sf is None:
                raise Refused(f"{c.name_of(sid) or sid} is not on the staff, so it holds no open items")
            if t.scope(sf.session) is not None:
                found = [(o, i) for o, i in found if _same(t, o, sf.session)]
            else:
                found = [(o, i) for o, i in found if i.get("held_by") and _same(t, i["held_by"], sf.session)]
        if self.waiting_on is not None:
            want = items_ops.resolve_wait(t, self.waiting_on)
            found = [(o, i) for o, i in found if _same(t, i.get("waiting_on"), want)]
        return sorted(found, key=lambda p: p[1]["id"])


def _same(t, a: str | None, b: str | None) -> bool:
    """Whether two `waiting_on` values are the same: equal, or two IDs of one staffer, across a rotate."""
    if a == b:
        return True
    sa, sb = t.staffer_now(a), t.staffer_now(b)
    return sa is not None and sb is not None and sa.session == sb.session
