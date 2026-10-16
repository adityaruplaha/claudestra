"""`claudestra enable-remote-control`: Remote Control on for every session, in Claude Code's user settings.

claudestra requires it (DESIGN.md §7.1), and `claudestra doctor remote-control` offers it. Turning it on
lets every session on the machine be reached and driven through the user's account, so it is the user's alone.
"""

from __future__ import annotations

from ..ops import remote_control
from .base import Action
from .permissions import Kinds


class EnableRemoteControl(Action):
    verb = "remote-control"
    who = Kinds(frozenset({"human"}))
    needs: list[str] = []

    def describe(self) -> list[str]:
        return remote_control.enable(self.context.fs, True)

    def run(self) -> list[str]:
        """The plan was shown before it ran, so it says only that it is done."""
        remote_control.enable(self.context.fs, False)
        return ["Remote Control is on for every session"]
