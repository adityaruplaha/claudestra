"""`claudestra session move`: refile a stopped session under another folder on this machine, as if it had always
run there: every store goes with it, and its cwd fields are rewritten (ops/move.py)."""

from __future__ import annotations

from pathlib import Path

from ..caller import Refused
from ..ops import memory as memory_ops
from ..ops import move as move_ops
from .base import FS_CHECKS, SessionAction
from .permissions import D_MANAGER, USER, Relations


class Move(SessionAction):
    verb = "move"
    who = Relations(frozenset({USER, D_MANAGER}))
    reversible = True
    needs = [*FS_CHECKS, "jobs"]  # it rewrites a background job's state as well

    def __init__(self, session, dest: Path, src: Path | None = None, exact: bool = False, copy_memory: bool = False):
        super().__init__(session)
        self.dest, self.src, self.exact, self.copy_memory = dest, src, exact, copy_memory
        self.plan: move_ops.MovePlan | None = None
        self.memory: list[tuple[str, list[str]]] = []  # (source slug, files to copy into the destination's)

    def check(self) -> None:
        c, r = self.context, self.session.record
        if r is None:
            raise Refused(f"{self.session.id} has no transcript on this machine")
        self.plan = move_ops.plan(c.fs, c.machine.hostname, c.trust, r, self.dest, self.src, self.exact)
        self.memory = []
        if self.copy_memory:
            have = memory_ops.local(c.fs, self.plan.dest_slug)
            for slug in r.homes:
                if slug != self.plan.dest_slug and (names := memory_ops.plan(memory_ops.local(c.fs, slug), have)):
                    self.memory.append((slug, names))

    def describe(self) -> list[str]:
        out = self.plan.describe(self.context.fs.home)
        out += [f"  memory {len(n)} files from {slug}, added to {self.plan.dest_slug}'s" for slug, n in self.memory]
        if self.copy_memory and not self.memory:
            out.append("  memory: nothing to copy")
        return out

    def run(self) -> None:
        c = self.context
        move_ops.apply(c.fs, c.machine.hostname, self.subject, self.plan)
        for slug, names in self.memory:  # copied, not moved: sessions left there may still read it
            memory_ops.copy_here(c.fs, slug, self.plan.dest_slug, names)

    def undo(self) -> None:
        """Move it back to the folder it came from."""
        back = Move(self.session, self.plan.src_folder, self.plan.dest_folder, self.exact)
        back.check()
        back.run()
        self.context.refresh()
