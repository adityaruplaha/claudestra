"""`claudestra move`: refile a stopped session under another folder on this machine, as if it had always
run there: every store goes with it, and its cwd fields are rewritten (ops/move.py)."""

from __future__ import annotations

from pathlib import Path

from ..caller import Refused
from ..ops import move as move_ops
from .base import SessionAction
from .permissions import D_MANAGER, USER, Relations


class Move(SessionAction):
    verb = "move"
    who = Relations(frozenset({USER, D_MANAGER}))
    reversible = True

    def __init__(self, session, dest: Path, src: Path | None = None, exact: bool = False):
        super().__init__(session)
        self.dest, self.src, self.exact = dest, src, exact
        self.plan: move_ops.MovePlan | None = None

    def check(self) -> None:
        c, r = self.context, self.session.record
        if r is None:
            raise Refused(f"{self.session.id} has no transcript on this machine")
        self.plan = move_ops.plan(c.fs, c.machine.hostname, c.trust, r, self.dest, self.src, self.exact)

    def describe(self) -> list[str]:
        return self.plan.describe(self.context.fs.home)

    def run(self) -> None:
        c = self.context
        move_ops.apply(c.fs, c.machine.hostname, self.subject, self.plan)

    def undo(self) -> None:
        """Move it back to the folder it came from."""
        back = Move(self.session, self.plan.src_folder, self.plan.dest_folder, self.exact)
        back.check()
        back.run()
        self.context.refresh()
