"""`claudestra check`: trust.yaml and staff.d/ against this machine."""

from __future__ import annotations

from ..ops import inspect
from .base import ReadOnlyAction


class Check(ReadOnlyAction):
    verb = "check"

    def run(self) -> tuple[list[str], list[str]]:
        """(problems, warnings)."""
        c = self.context
        return inspect.config_report(c.fs, c.trust, c.machine.hostname)
