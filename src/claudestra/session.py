"""A session, by its ID, and a staffer, a session on the staff (DESIGN.md §4).

The ID is all either holds, since it is the only thing about a session that never changes. Everything
else is read from the context's model when asked, so a session read before the lock is read afresh
after `Context.refresh()`. Its methods are the actions on it, as factories that do nothing yet.
"""

from __future__ import annotations

from pathlib import Path

from . import portable
from .caller import Refused
from .context import Context
from .model import Job, Run, SessionRecord
from .ops.common import Stores, stores
from .runners import Launch
from .trust import StaffFile


class Session:
    def __init__(self, session_id: str):
        self.id = session_id

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Session) and other.id == self.id

    def __hash__(self) -> int:
        return hash(self.id)

    def __repr__(self) -> str:
        return f"Session({self.id!r})"

    # --- what it is, read now ---------------------------------------------------------------

    @property
    def record(self) -> SessionRecord | None:
        """This machine's record of it, or None where it has no transcript here."""
        return Context.current().model.sessions.get(self.id)

    @property
    def here(self) -> bool:
        return self.record is not None

    def _get(self, attr: str, default):
        r = self.record
        return getattr(r, attr) if r is not None else default

    @property
    def name(self) -> str | None:
        return self._get("name", None)

    @property
    def names(self) -> list[str]:
        return self._get("names", [])

    @property
    def homes(self) -> list[str]:
        return self._get("homes", [])

    @property
    def folder(self) -> Path | None:
        return self._get("folder", None)

    @property
    def runs(self) -> list[Run]:
        return self._get("runs", [])

    @property
    def jobs(self) -> list[Job]:
        return self._get("jobs", [])

    @property
    def state(self) -> str:
        r = self.record
        return r.state if r is not None else "not on this machine"

    @property
    def mtime(self) -> float:
        return self._get("mtime", 0.0)

    @property
    def transcript(self) -> Path | None:
        homes = self.homes
        return Context.current().fs.transcript(homes[0], self.id) if len(homes) == 1 else None

    @property
    def running_pid(self) -> int | None:
        """The pid of its live run on this machine, if it is running."""
        c = Context.current()
        return portable.running_pid(c.fs.sessions, c.fs.proc, self.id)

    @property
    def stores(self) -> Stores | None:
        """Every file Claude Code keeps for it on this machine, or None where it has no transcript here."""
        r, c = self.record, Context.current()
        if r is None:
            return None
        meta = c.fs.read_meta(c.fs.transcript(r.homes[0], self.id), self.id) if len(r.homes) == 1 else None
        return stores(c.fs, r, meta.secondary_ids if meta else frozenset())

    def window(self, socket: str | None = None):
        """Its window in claudestra's tmux (named by its session ID), or None. A method, not a property,
        since a test names its own tmux server."""
        from .actions.base import tmux

        return tmux(socket).window(self.id)

    @property
    def protected(self) -> bool:
        homes = self.homes
        return Context.current().trust.is_protected(self.folder, homes[0] if homes else None)

    # --- on the staff or not, and how it is run ------------------------------------------------

    @property
    def on_staff(self) -> bool:
        """Whether a staff file names it, read now. A caller that needs the staffer asks the context for
        it (`Context.staffer`); one that does not care leaves it a session."""
        return Context.current().trust.staff_file(self.id) is not None

    @property
    def launch(self) -> Launch:
        """How a runner starts it: by its title, in the folder it is filed under."""
        if self.folder is None:
            raise Refused(
                f"the folder {self.id} is filed under is not known, so claudestra cannot resume it there without forking it"
            )
        return Launch(self.id, self.name or self.id[:8], self.folder)

    # --- the actions on it ------------------------------------------------------------------

    def show(self):
        from .actions.show import Show

        return Show(self)

    def summary(self, reply_chars: int = 1500):
        from .actions.summary import Summary

        return Summary(self, reply_chars)

    def rename(self, name: str, socket: str | None = None):
        from .actions.rename import Rename

        return Rename(self, name, socket)

    def type(self, text: str, socket: str | None = None):
        from .actions.type import Type

        return Type(self, text, socket)

    def start(self, claude: str, socket: str | None = None):
        from .actions.start import Start

        return Start(self, claude, socket)

    def stop(self, force: bool = False, socket: str | None = None):
        from .actions.stop import Stop

        return Stop(self, force, socket)

    def move(self, dest: Path, src: Path | None = None, exact: bool = False):
        from .actions.move import Move

        return Move(self, dest, src, exact)

    def trash(self, recent_minutes: float = 10.0):
        from .actions.trash import Trash

        return Trash(self, recent_minutes)

    def send(self, host: str, dest: str | None = None, src: Path | None = None):
        from .actions.send import Send

        return Send(self, host, dest, src)

    def compact(self, claude: str, instructions: str = "", timeout: float = 600.0, socket: str | None = None):
        from .actions.compact import Compact

        return Compact(self, claude, instructions, timeout, socket)

    def hire(self, name: str | None = None, folder: Path | None = None, description: str | None = None):
        from .actions.hire import Hire

        return Hire(self, name, folder, description)


class Staffer(Session):
    """A session on the staff: one a staff file, staff.d/<session ID>.yaml, names, giving it a name, a
    folder on each machine and a job. Got from the context (`Context.staffer`) by a caller that needs
    one. Whether a session is on the staff can change at any time, so the staff file is read each time
    it is asked for, and refused once it is gone."""

    def __repr__(self) -> str:
        return f"Staffer({self.id!r})"

    @property
    def staff_file(self) -> StaffFile:
        sf = Context.current().trust.staff_file(self.id)
        if sf is None:
            raise Refused(f"{self.id} is no longer on the staff")
        return sf

    @property
    def staff_name(self) -> str:
        """Its name on the staff, as its staff file gives it; its title is `name`."""
        return self.staff_file.name

    @property
    def scope(self) -> str | None:
        return Context.current().trust.scope(self.id)

    @property
    def autostart(self) -> bool:
        c = Context.current()
        return self.id in c.trust.autostart(c.machine.hostname)

    @property
    def managers(self) -> list[Staffer]:
        """The folder-scope staffers whose folder holds this one's."""
        return [Staffer(m.session) for m in Context.current().trust.managers_over(self.staff_file)]

    @property
    def managed_by(self) -> str:
        """Who it answers to: its managers, or with none this machine's device scope."""
        return Context.current().trust.managed_by(self.staff_file)

    @property
    def launch(self) -> Launch:
        """How a runner starts it: by its name on the staff, in the folder its staff file gives here."""
        sf = self.staff_file
        if sf.folder is None:
            raise Refused(f"{sf.file.name} gives no folder for {Context.current().machine.hostname}")
        return Launch(self.id, sf.name, sf.folder)

    # --- the actions only a staffer has --------------------------------------------------------

    def fix_name(self):
        from .actions.set_staff_name import SetStaffName

        return SetStaffName(self)

    def dismiss(self, socket: str | None = None):
        from .actions.dismiss import Dismiss

        return Dismiss(self, socket)

    def set_description(self, description: str):
        from .actions.describe import Describe

        return Describe(self, description)
