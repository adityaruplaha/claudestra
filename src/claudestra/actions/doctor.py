"""`claudestra doctor`: every fact about Claude Code's files that claudestra relies on, checked here."""

from __future__ import annotations

from .. import checks
from ..caller import Refused
from .base import ReadOnlyAction


class Doctor(ReadOnlyAction):
    verb = "doctor"

    def __init__(self, names: list[str] | None = None, deep: bool = False):
        super().__init__()
        self.names, self.deep = names, deep

    def check(self) -> None:
        if bad := [n for n in self.names or [] if n not in checks.CHECKS]:
            raise Refused(f"no such check: {', '.join(bad)}; choose from {', '.join(checks.CHECKS)}")

    def run(self) -> list[checks.Result]:
        c = self.context
        return checks.run(c.fs, self.names or None, self.deep, c.trust, c.machine)
