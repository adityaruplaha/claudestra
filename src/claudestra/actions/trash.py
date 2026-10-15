"""`claudestra trash`: move a stopped session to the trash, every store with it; `restore` puts it back."""

from __future__ import annotations

from pathlib import Path

from ..caller import Refused
from ..ops import trash as trash_ops
from .base import SessionAction
from .permissions import D_OTHER, USER, Relations


class Trash(SessionAction):
    verb = "trash"
    who = Relations(frozenset({USER, D_OTHER}))
    reversible = True

    def __init__(self, session, recent_minutes: float = 10.0):
        super().__init__(session)
        self.recent_minutes = recent_minutes
        self.plan: trash_ops.Plan | None = None
        self.entry: Path | None = None

    def check(self) -> None:
        c, r = self.context, self.session.record
        if r is None:
            raise Refused(f"{self.session.id} has no transcript on this machine")
        if self.session.on_staff:
            raise Refused(f"{self.context.name_of(self.session.id)!r} is on the staff; dismiss it first")
        self.plan = trash_ops.plan(c.fs, c.trust, r, self.recent_minutes)

    def describe(self) -> list[str]:
        p = self.plan
        return [
            f"trash {p.session.session_id} ({p.session.name or '-'}): {len(p.items)} stores, {p.bytes / 1e6:.2f} MB"
        ]

    def run(self) -> Path:
        self.entry = trash_ops.apply(self.context.fs, self.subject, self.plan)
        return self.entry

    def undo(self) -> None:
        trash_ops.restore(self.context.fs, self.subject, self.entry.name, dry=False)
        self.context.refresh()
