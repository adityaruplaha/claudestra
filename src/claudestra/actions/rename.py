"""`claudestra rename`: rename a session as /rename does inside one.

A stopped session's files are written as /rename writes them (ops/rename.py). A running Claude Code
re-appends its own title records, and the last one wins, so a running staffer in claudestra's tmux has
/rename typed into its window instead. A staffer's staff file follows, changing only its name line.
"""

from __future__ import annotations

from ..caller import Refused
from ..ops import rename as rename_ops
from ..ops.common import log, refuse_if_running
from ..trust import set_staff_name
from .base import SessionAction, tmux
from .permissions import D_MANAGED, D_MANAGER, D_UNMANAGED, MANAGER, USER, Relations


class Rename(SessionAction):
    verb = "rename"
    who = Relations(frozenset({USER, MANAGER, D_MANAGER, D_UNMANAGED, D_MANAGED}))
    reversible = True

    def __init__(self, session, name: str, socket: str | None = None):
        super().__init__(session)
        self.name, self.socket = name, socket
        self.new = self.window = None
        self.old: str | None = None  # the session's title before, and its staff file's name before
        self.old_staff_name: str | None = None

    def check(self) -> None:
        from ..runners import tmux as runner

        c, s = self.context, self.session
        r = s.record
        if r is None:
            raise Refused(f"{s.id} has no transcript on this machine")
        self.new = rename_ops.check(c.trust, r, self.name)
        self.window = None
        if r.runs:
            self.window = runner.window_to_type_into(c.fs, tmux(self.socket), s.id)
        else:
            refuse_if_running(c.fs, r)

    @property
    def staffer(self):
        """The session as a staffer, if it is on the staff, whose staff file's name follows."""
        s = self.session
        return self.context.staffer(s.id) if s.on_staff else None

    def describe(self) -> list[str]:
        s, st = self.session, self.staffer
        how = f", by typing /rename into its window {self.window.id}" if self.window else ""
        staff_file = f" (and its staff file {st.staff_file.file.name})" if st else ""
        return [f"rename {s.id}: {s.name!r} -> {self.new!r}{how}{staff_file}"]

    def run(self) -> None:
        from ..runners import tmux as runner

        c, s, st = self.context, self.session, self.staffer
        self.old, self.old_staff_name = s.name, st.staff_name if st else None
        if self.window is None:
            rename_ops.write(c.fs, self.subject, s.record, self.new)
            return
        title = s.transcript.parent / s.id / "custom-title.json"
        runner.rename_in_window(c.fs, tmux(self.socket), s.id, title, self.window, self.new)
        if st:
            set_staff_name(st.staff_file, self.new)
        log(self.subject, "rename", s.id, f"{self.old!r} -> {self.new!r} (typed into {self.window.id})")

    def undo(self) -> None:
        """Put the session's title back, and its staff file's name, each to what it was."""
        if self.old is None:
            return
        staff_name = self.old_staff_name
        self.name = self.old
        self.check()
        self.run()
        self.context.refresh()
        if staff_name is not None and (st := self.staffer) is not None:
            set_staff_name(st.staff_file, staff_name)
            self.context.refresh()
