"""`claudestra describe`: change what a staffer's staff file says it works on. Whoever may hire the staffer
may describe it, since stating a specialist's work is part of supervising it, and so may the staffer
itself; only the description line changes, and claudestra writes it, since staff.d/ is claudestra's to
write (DESIGN.md §6.2)."""

from __future__ import annotations

from ..caller import Refused
from ..ops.common import log
from ..trust import update_staff_file
from .base import SessionAction
from .permissions import D_UNMANAGED, MANAGER, SELF, USER, Relations


class Describe(SessionAction):
    """On a staffer (claudestra.session.Staffer), whose staff file it changes."""

    verb = "describe"
    who = Relations(frozenset({USER, SELF, MANAGER, D_UNMANAGED}))  # as for hire, and the staffer itself
    reversible = True

    def __init__(self, staffer, description: str):
        super().__init__(staffer)
        self.description = description.strip()
        self.old: str | None = None

    @property
    def staffer(self):
        return self.object

    def check(self) -> None:
        if not self.description:
            raise Refused("a description says what the staffer works on, so it cannot be empty")
        if self.description == self.staffer.staff_file.description:  # refuses one no longer on the staff
            raise Refused(f"{self.staffer.staff_name!r} already has that description")

    def describe(self) -> list[str]:
        st = self.staffer
        return [
            f"staff file {st.staff_file.file.name}: description {st.staff_file.description!r} -> {self.description!r}"
        ]

    def run(self) -> None:
        st = self.staffer
        self.old = st.staff_file.description
        update_staff_file(st.staff_file, lambda raw: raw.__setitem__("description", self.description))
        log(self.subject, "describe", st.id, f"{self.old!r} -> {self.description!r}")

    def undo(self) -> None:
        update_staff_file(self.staffer.staff_file, lambda raw: raw.__setitem__("description", self.old))
        self.context.refresh()
