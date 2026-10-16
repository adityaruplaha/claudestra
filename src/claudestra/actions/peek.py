"""`claudestra session peek`: the screen of a session running in claudestra's tmux, without attaching, so a
manager can see a staffer held at a question or a permission prompt. It reads and changes nothing, so it is
anyone's, like reading a transcript."""

from __future__ import annotations

from ..caller import Refused
from .base import ReadOnlyAction, tmux


class Peek(ReadOnlyAction):
    verb = "peek"

    def __init__(self, session, lines: int = 40, socket: str | None = None):
        super().__init__(session)
        self.lines, self.socket = lines, socket

    def run(self) -> list[str]:
        t = tmux(self.socket)
        w = t.window(self.object.id)
        if w is None:
            raise Refused(f"{self.object.id} is not running in claudestra's tmux, so there is no screen to show")
        return t.screen(w.id, self.lines)
