"""`claudestra hire`: put a session on the staff, by writing its staff file.

The staff file is claudestra's to write, so hiring is the only way onto the staff. A session that was
dismissed is rehired from its old staff file, with whatever is given here written over it. Who may
hire is worked out from the folder the staffer will work in, as the relation the subject would have
to it once hired: the user; a manager, into its own folder; a device scope, where no manager holds the
folder. A session never hires itself.
"""

from __future__ import annotations

from pathlib import Path

from ..caller import Refused, transcript_problem
from ..ops import staff as staff_ops
from ..ops.common import log
from ..ops.rename import check_name
from ..trust import tilde
from .base import SessionAction
from .permissions import D_UNMANAGED, MANAGER, USER, ToFolder


class Hire(SessionAction):
    verb = "hire"
    who = ToFolder(frozenset({USER, MANAGER, D_UNMANAGED}))
    needs: list[str] = ["slug-rule"]
    reversible = True

    def __init__(self, session, name: str | None = None, folder: Path | None = None, description: str | None = None):
        super().__init__(session)
        self.name, self.folder, self.description = name, folder, description
        self.plan: tuple[str, dict[str, str], str, Path] | None = None  # name, folders, description, folder here
        self.was_dismissed: str | None = None

    def check(self) -> None:
        c, s = self.context, self.session
        if s.on_staff:
            raise Refused(f"{s.id} is on the staff already")
        if not s.here:
            raise Refused(f"{s.id} has no transcript on this machine; hire it where it lives")
        old = staff_ops.dismissed(c.trust.config, s.id) or {}
        host, home = c.machine.hostname, c.fs.home
        folders = {str(h): v for h, v in (old.get("folder") or {}).items() if str(h).lower() != host.lower()}
        here = self.folder or s.folder
        if here is None:
            raise Refused(f"the folder {s.id} is filed under is not known; give it with --folder")
        here = Path(here).expanduser().absolute()
        if why := transcript_problem(c.fs, host, s.id, here):
            raise Refused(f"it cannot work in {here}: {why}")
        folders[host] = tilde(here, home)
        name = check_name(self.name or old.get("name") or s.name or "")
        if clash := next((f for f in c.trust.staff if f.name == name), None):
            raise Refused(f"the staffer {clash.session} is already named {name!r}; give another with --name")
        description = (self.description or old.get("description") or "").strip()
        if not description:
            raise Refused("a staffer's description says what it works on; give one with --description")
        self.plan = (name, folders, description, here)

    @property
    def folder_here(self) -> Path:
        """The folder it will work in on this machine, which decides who may hire it (ToFolder)."""
        here = self.plan[3] if self.plan else (self.folder or self.session.folder)
        if here is None:
            raise Refused(f"the folder {self.session.id} would work in is not known; give it with --folder")
        return Path(here).expanduser().absolute()

    def describe(self) -> list[str]:
        name, folders, description, _ = self.plan
        s = self.session
        again = (
            " again, from staff-dismissed.d/"
            if staff_ops.dismissed_path(self.context.trust.config, s.id).exists()
            else ""
        )
        where = ", ".join(f"{h}: {v}" for h, v in folders.items())
        return [f"hire {s.id} ({s.name or '-'}){again} as {name!r}, working in {where}: {description}"]

    def run(self) -> None:
        c, s = self.context, self.session
        name, folders, description, _ = self.plan
        d = staff_ops.dismissed_path(c.trust.config, s.id)
        self.was_dismissed = d.read_text() if d.exists() else None
        staff_ops.hire(c.trust.config, s.id, name, folders, description)
        log(self.subject, "hire", s.id, f"as {name!r}")

    def undo(self) -> None:
        staff_ops.unhire(self.context.trust.config, self.session.id, self.was_dismissed)
        self.context.refresh()
