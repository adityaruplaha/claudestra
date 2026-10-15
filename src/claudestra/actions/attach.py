"""`claudestra attach`: join claudestra's tmux session. The user's alone; it replaces this process with tmux."""

from __future__ import annotations

import os

from ..runners import TMUX_SESSION
from .base import Action
from .permissions import Kinds


class Attach(Action):
    verb = "attach"
    who = Kinds(frozenset({"human"}))
    needs: list[str] = []
    locks = False  # this process becomes tmux, which would hold the lock for as long as the user is attached

    def __init__(self, socket: str | None = None):
        super().__init__()
        self.socket = socket

    def describe(self) -> list[str]:
        return [f"attach to tmux session {TMUX_SESSION}"]

    def run(self) -> None:
        sock = ["-L", self.socket] if self.socket else []
        verb = "switch-client" if os.environ.get("TMUX") else "attach-session"
        os.execvp("tmux", ["tmux", *sock, verb, "-t", f"={TMUX_SESSION}"])
