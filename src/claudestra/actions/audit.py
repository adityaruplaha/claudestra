"""`claudestra audit`: what needs attention among this machine's sessions."""

from __future__ import annotations

from ..audit_errors import AuditError
from ..caller import Refused
from ..ops.audit import REPORTS
from .base import ReadOnlyAction


class Audit(ReadOnlyAction):
    verb = "audit"

    def __init__(self, reports: list[str] | None = None):
        super().__init__()
        self.reports = reports or list(REPORTS)

    def check(self) -> None:
        if bad := [r for r in self.reports if r not in REPORTS]:
            raise Refused(f"no such report: {', '.join(bad)}; choose from {', '.join(REPORTS)}")

    def run(self) -> dict[str, list[AuditError]]:
        c = self.context
        return {name: REPORTS[name](c.fs, c.model) for name in self.reports}
