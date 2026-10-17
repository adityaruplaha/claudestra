"""`claudestra staff local-folder remove`: take this machine's folder out of the staff file of a staffer whose
session lives on another machine, undoing `local-folder assign`. Only for a staffer with no transcript here, and
only while its staff file names another machine's folder, so that it keeps one. Whose it is, is as for assign."""

from __future__ import annotations

from ..caller import Refused
from ..ops.common import log
from ..trust import tilde, update_staff_file
from .assign_local_folder import AssignLocalFolder
from .base import SessionAction


class RemoveLocalFolder(SessionAction):
    """On a staffer (claudestra.session.Staffer), whose staff file it changes."""

    verb = "local-folder remove"
    who = AssignLocalFolder.who
    reversible = True

    def __init__(self, staffer):
        super().__init__(staffer)
        self.old: dict | None = None

    @property
    def staffer(self):
        return self.object

    def check(self) -> None:
        st, host = self.staffer, self.context.machine.hostname
        if st.here:
            raise Refused(f"{st.staff_name!r} lives on {host}, so its folder here is where its session is filed")
        sf = st.staff_file
        if sf.folder is None:
            raise Refused(f"{st.staff_name!r} has no folder on {host}")
        if not [h for h in sf.folders if str(h).lower() != host.lower()]:
            raise Refused(f"{st.staff_name!r} has a folder only on {host}; its staff file would be left with none")

    def describe(self) -> list[str]:
        sf, c = self.staffer.staff_file, self.context
        return [f"staff file {sf.file.name}: folder on {c.machine.hostname} {tilde(sf.folder, c.fs.home)} removed"]

    def run(self) -> None:
        st, host = self.staffer, self.context.machine.hostname
        self.old, gone = dict(st.staff_file.folders), st.staff_file.folder
        kept = {h: f for h, f in self.old.items() if str(h).lower() != host.lower()}
        update_staff_file(st.staff_file, lambda raw: raw.__setitem__("folder", kept))
        log(self.subject, "local-folder remove", st.id, tilde(gone, self.context.fs.home))

    def undo(self) -> None:
        old = self.old
        update_staff_file(self.staffer.staff_file, lambda raw: raw.__setitem__("folder", old))
        self.context.refresh()
