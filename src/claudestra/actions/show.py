"""`claudestra show`: one session in full."""

from __future__ import annotations

from ..caller import Refused
from ..ops import inspect
from .base import ReadOnlyAction


class Show(ReadOnlyAction):
    verb = "show"

    def check(self) -> None:
        if not self.object.here:
            raise Refused(f"{self.object.id} has no transcript on this machine")

    def run(self) -> dict:
        c = self.context
        r = self.object.record
        return inspect.session_info(c.fs, c.trust, c.model, r, c.machine.hostname, r.state)
