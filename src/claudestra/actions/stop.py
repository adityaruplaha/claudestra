"""`claudestra session stop`: stop a session running in claudestra's tmux; its conversation is kept."""

from __future__ import annotations

from ..ops.common import log
from .base import SessionAction, tmux
from .permissions import D_MANAGER, D_UNMANAGED, MANAGER, USER, Relations


class Stop(SessionAction):
    verb = "stop"
    who = Relations(frozenset({USER, MANAGER, D_MANAGER, D_UNMANAGED}))
    needs = ["pid-files", "proc-start", "slug-rule"]

    def __init__(self, session, force: bool = False, socket: str | None = None):
        super().__init__(session)
        self.force, self.socket = force, socket

    def describe(self) -> list[str]:
        from ..runners import tmux as runner

        return [
            runner.stop(self.context.fs, tmux(self.socket), self.session.id, self.label, dry=True, force=self.force)
        ]

    def run(self) -> str:
        from ..runners import tmux as runner

        line = runner.stop(self.context.fs, tmux(self.socket), self.session.id, self.label, dry=False, force=self.force)
        if line.startswith(("stopped", "cleared")):
            log(self.subject, "stop", self.session.id, line)
        return line
