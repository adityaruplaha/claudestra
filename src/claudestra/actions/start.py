"""`claudestra start`: resume a session in claudestra's tmux, with Remote Control on.

Any session whose folder is known can be started. A staffer runs by its name on the staff, from the
folder its staff file gives; any other session by its title, from the folder it is filed under. Who
may start which is the relation's: a session off the staff is the user's alone.
"""

from __future__ import annotations

from ..context import Context
from ..ops.common import log
from ..runners import Launch
from .base import SessionAction, tmux
from .permissions import D_MANAGER, D_UNMANAGED, LOGIN_AUTOSTART, MANAGER, USER, Relations


def launch(session) -> Launch:
    """How to run the session: a staffer's from its staff file, any other's from where it is filed."""
    c = Context.current()
    return c.staffer(session.id).launch if session.on_staff else session.launch


class Start(SessionAction):
    verb = "start"
    who = Relations(frozenset({USER, MANAGER, D_MANAGER, D_UNMANAGED, LOGIN_AUTOSTART}))
    needs = ["pid-files", "proc-start", "slug-rule"]

    def __init__(self, session, claude: str, socket: str | None = None):
        super().__init__(session)
        self.claude, self.socket = claude, socket

    def check(self) -> None:
        launch(self.session)  # refuses a session whose folder is not known

    def describe(self) -> list[str]:
        from ..runners import tmux as runner

        c = self.context
        return [runner.start(c.fs, c.machine.hostname, tmux(self.socket), launch(self.session), self.claude, dry=True)]

    def run(self) -> str:
        from ..runners import tmux as runner

        c = self.context
        line = runner.start(c.fs, c.machine.hostname, tmux(self.socket), launch(self.session), self.claude, dry=False)
        if line.startswith(("started", "exited")):
            log(self.subject, "start", self.session.id, line)
        return line
