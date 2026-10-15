"""`claudestra type`: type one line into a staffer running in claudestra's tmux, and press Enter.

Refused while the staffer is mid-turn or its prompt holds unsent text, so nothing anyone was writing is
sent or overwritten; a dimmed suggestion does not count, since typing replaces it.
"""

from __future__ import annotations

from ..ops.common import log
from .base import SessionAction, tmux
from .permissions import D_DEVICE, D_MANAGED, D_MANAGER, D_UNMANAGED, MANAGER, USER, Relations


class Type(SessionAction):
    verb = "type"
    who = Relations(frozenset({USER, MANAGER, D_MANAGER, D_UNMANAGED, D_MANAGED, D_DEVICE}))
    needs = ["pid-files", "proc-start"]

    def __init__(self, session, text: str, socket: str | None = None):
        super().__init__(session)
        self.text, self.socket = text, socket
        self.window = None

    def check(self) -> None:
        from ..runners import tmux as runner

        runner.check_text(self.text)
        self.window = runner.window_to_type_into(self.context.fs, tmux(self.socket), self.session.id)

    def describe(self) -> list[str]:
        return [f"type into {self.label} ({self.session.id[:8]}, window {self.window.id}): {self.text}"]

    def run(self) -> None:
        from ..runners import tmux as runner

        runner.type_into(self.context.fs, tmux(self.socket), self.session.id, self.window, self.text)
        log(self.subject, "type", self.session.id, self.text)
