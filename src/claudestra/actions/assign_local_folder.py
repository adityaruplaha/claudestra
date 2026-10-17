"""`claudestra staff local-folder assign`: give a staffer whose session lives on another machine a folder on this
one, in its staff file, so that it can be moved or fetched here and is listed with a folder. Only for a staffer
with no transcript here: one that lives here has its folder from where its session is filed, and `session move`
changes it; `local-folder remove` takes the folder away again. Not for a device scope while
the user's preference `device-scopes-machine-bound` holds; with it off, a device scope gets a warning. The user's, and a device scope's, since the device scope answers for what is on its machine; the
staffer's own manager is on the other machine. Who may act on the staffer is unchanged."""

from __future__ import annotations

from pathlib import Path

from ..caller import Refused
from ..ops import preferences as prefs
from ..ops.common import log
from ..portable import given_folder
from ..trust import set_staff_folder, tilde, update_staff_file
from .base import SessionAction
from .permissions import D_DEVICE, D_MANAGED, D_MANAGER, D_UNMANAGED, USER, Relations


class AssignLocalFolder(SessionAction):
    """On a staffer (claudestra.session.Staffer), whose staff file it changes."""

    verb = "local-folder assign"
    who = Relations(frozenset({USER, D_MANAGER, D_UNMANAGED, D_MANAGED, D_DEVICE}))
    reversible = True

    def __init__(self, staffer, folder: Path):
        super().__init__(staffer)
        self.folder = given_folder(folder)
        self.old: dict | None = None

    @property
    def staffer(self):
        return self.object

    def check(self) -> None:
        st, host = self.staffer, self.context.machine.hostname
        if st.here:
            raise Refused(
                f"{st.staff_name!r} lives on {host}, so its folder is where its session is filed; `session move` changes it"
            )
        if st.scope == "device" and prefs.device_scopes_bound(self.context.trust.config):
            raise Refused(f"{st.staff_name!r} is a device scope, bound to its own machine ({prefs.UNBIND})")
        if not self.folder.is_dir():
            raise Refused(f"{self.folder} is not a folder on {host}")
        if st.staff_file.folder == self.folder:
            raise Refused(f"{st.staff_name!r} already has {tilde(self.folder, self.context.fs.home)} on {host}")

    def describe(self) -> list[str]:
        sf, c = self.staffer.staff_file, self.context
        old = tilde(sf.folder, c.fs.home) if sf.folder else "none"
        warn = (
            [
                f"warning: {self.staffer.staff_name!r} is a device scope; it gets a folder on a machine it does not run on"
            ]
            if self.staffer.scope == "device"
            else []
        )
        return warn + [
            f"staff file {sf.file.name}: folder on {c.machine.hostname} {old} -> {tilde(self.folder, c.fs.home)}"
        ]

    def run(self) -> None:
        st, c = self.staffer, self.context
        self.old = dict(st.staff_file.folders)
        set_staff_folder(st.staff_file, c.machine.hostname, self.folder, c.fs.home)
        log(self.subject, "local-folder assign", st.id, tilde(self.folder, c.fs.home))

    def undo(self) -> None:
        old = self.old
        update_staff_file(self.staffer.staff_file, lambda raw: raw.__setitem__("folder", old))
        self.context.refresh()
