"""`claudestra purge`: delete trash entries older than some days, for good. The user's alone."""

from __future__ import annotations

from pathlib import Path

from ..ops import trash as trash_ops
from .base import Action
from .permissions import Kinds


class Purge(Action):
    verb = "purge"
    who = Kinds(frozenset({"human"}))
    needs: list[str] = []

    def __init__(self, older_than_days: float):
        super().__init__()
        self.older_than_days = older_than_days
        self.doomed: list[Path] = []

    def check(self) -> None:
        self.doomed = trash_ops.purgeable(self.context.fs, self.older_than_days)

    def describe(self) -> list[str]:
        return [f"delete {e.name}" for e in self.doomed]

    def run(self) -> list[str]:
        return trash_ops.purge(self.context.fs, self.subject, self.doomed)
