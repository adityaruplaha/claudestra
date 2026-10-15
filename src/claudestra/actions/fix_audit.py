"""`claudestra audit --fix`: fix the trivial drift the audit finds, as a development tool's --fix does.

An audit error that claudestra can fix safely says how (`AuditError.fix()`, audit_errors.py): today, an
staffer's staff file name following its session's title (NameMismatch). A folder change is only reported, never
followed, since following one could widen a manager's reach. Each fix is authorized on its own; the ones
the caller may take run together as a transaction, and the rest are reported as skipped, with the reason.
"""

from __future__ import annotations

from ..caller import Refused
from .base import Action, Transaction
from .permissions import Anyone


class FixAudit(Action):
    verb = "fix the audit"
    who = Anyone("each fix is authorized as its own verb")
    needs: list[str] = []

    def __init__(self, reports: list[str] | None = None):
        super().__init__()
        self.reports = reports
        self.fixes: list[Action] = []
        self.skipped: list[str] = []

    def check(self) -> None:
        from .audit import Audit

        self.fixes, self.skipped = [], []
        for errors in Audit(self.reports).perform().values():
            for error in errors:
                if (fix := error.fix()) is None:
                    continue
                try:
                    fix.check()
                    fix.authorize()
                except Refused as e:
                    self.skipped.append(f"skip {error.subject}: {e}")
                    continue
                self.fixes.append(fix)

    def describe(self) -> list[str]:
        return [line for f in self.fixes for line in f.describe()] + self.skipped

    def run(self) -> list[str]:
        done = [line for f in self.fixes for line in f.describe()]
        if self.fixes:
            Transaction(self.fixes).run()
        return done
