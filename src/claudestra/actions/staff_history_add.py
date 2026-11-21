"""`claudestra staff history add`: record a session a staffer had before, as `staff rotate` does, for a staffer
given a new session some other way (a spawn and a dismissal), so that an ID written before still reaches it.
Who may describe the staffer may add to its history: the user, its manager, the device scope where no manager
holds it, and the staffer itself."""

from __future__ import annotations

import datetime as _dt

from .. import portable
from ..caller import Refused
from ..claude_fs import UUID
from ..ops import staff as staff_ops
from ..ops.common import log
from .base import SessionAction
from .permissions import D_UNMANAGED, MANAGER, SELF, USER, Relations


class StaffHistoryAdd(SessionAction):
    """On a staffer (claudestra.session.Staffer), whose staff file it changes."""

    verb = "staff history add"
    who = Relations(frozenset({USER, SELF, MANAGER, D_UNMANAGED}))  # as for describe
    needs: list[str] = []
    reversible = True

    def __init__(self, staffer, session_id: str, at: str | None = None, reason: str | None = None):
        super().__init__(staffer)
        self.old, self.at = session_id.strip().lower(), (at or "").strip() or portable.now_local()
        self.reason = (reason or "").strip()
        self.before: str | None = None

    @property
    def staffer(self):
        return self.object

    def check(self) -> None:
        t, sf = self.context.trust, self.staffer.staff_file  # refuses one no longer on the staff
        if not UUID.match(self.old):
            raise Refused("give the old session's full ID")
        if self.old == sf.session:
            raise Refused(f"{self.old} is the session of {sf.name!r} now, not one it had before")
        if (other := t.staffer_now(self.old)) is not None:
            raise Refused(f"{self.old} is a session of {other.name!r} already")
        try:
            at = _dt.datetime.fromisoformat(self.at)
        except ValueError:
            raise Refused(f"--at {self.at!r} is not an ISO time, such as 2026-11-21T14:05:00+08:00") from None
        if at.tzinfo is None:
            raise Refused("--at needs its UTC offset, such as +08:00, so that it is one exact time")
        if not self.reason:
            raise Refused("say why it was rotated, with --reason")

    def describe(self) -> list[str]:
        sf = self.staffer.staff_file
        return [f"staff file {sf.file.name}: history adds {self.old}, rotated {self.at}: {self.reason}"]

    def run(self) -> None:
        sf = self.staffer.staff_file
        self.before = sf.file.read_text()
        staff_ops.add_history(sf.file, self.old, self.at, self.reason)
        log(self.subject, "staff history add", sf.session, f"{self.old} at {self.at}: {self.reason}")

    def undo(self) -> None:
        portable.atomic_write_text(self.staffer.staff_file.file, self.before)
        self.context.refresh()
