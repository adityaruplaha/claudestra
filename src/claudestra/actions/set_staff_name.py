"""Bring a staffer's staff file name into step with its session's title, as after a /rename typed inside the
session. Only the staff file's name line changes. `audit --fix` takes it for every staffer that drifted."""

from __future__ import annotations

from ..caller import Refused
from ..ops.common import log
from ..trust import set_staff_name
from .base import SessionAction
from .permissions import D_MANAGED, D_MANAGER, D_UNMANAGED, MANAGER, SELF, USER, Relations


class SetStaffName(SessionAction):
    """On a staffer (claudestra.session.Staffer), whose staff file it changes."""

    verb = "fix-name"
    # Who may rename the staffer, and the staffer itself: its staff file is its own to keep.
    who = Relations(frozenset({USER, SELF, MANAGER, D_MANAGER, D_UNMANAGED, D_MANAGED}))
    reversible = True

    def __init__(self, staffer):
        super().__init__(staffer)
        self.old: str | None = None

    @property
    def staffer(self):
        return self.object

    def check(self) -> None:
        st = self.staffer
        if not st.here:
            raise Refused(f"{st.id} has no transcript on this machine")
        if not st.name or st.name == st.staff_name:  # staff_name refuses one no longer on the staff
            raise Refused(f"{st.staff_name!r} already matches its session's title")
        if clash := next((f for f in self.context.trust.staff if f.name == st.name and f.session != st.id), None):
            raise Refused(f"the staffer {clash.session} is already named {st.name!r}; rename one of them first")

    def describe(self) -> list[str]:
        st = self.staffer
        return [f"staff file {st.staff_file.file.name}: name {st.staff_name!r} -> {st.name!r}, its session's title"]

    def run(self) -> None:
        st = self.staffer
        self.old = st.staff_name
        set_staff_name(st.staff_file, st.name)
        log(self.subject, "fix-name", st.id, f"{self.old!r} -> {st.name!r}")

    def undo(self) -> None:
        set_staff_name(self.staffer.staff_file, self.old)
        self.context.refresh()
