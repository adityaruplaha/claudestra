"""`claudestra restore`: put a trashed session back where it came from."""

from __future__ import annotations

from ..ops import trash as trash_ops
from .base import Action
from .permissions import Kinds


class Restore(Action):
    verb = "restore"
    who = Kinds(frozenset({"human", "device"}))
    needs: list[str] = []

    def __init__(self, entry: str):
        super().__init__(entry)
        self.would: list[str] = []

    def check(self) -> None:
        self.would = trash_ops.restore(self.context.fs, self.subject, self.object, dry=True)

    def describe(self) -> list[str]:
        return self.would

    def run(self) -> list[str]:
        return trash_ops.restore(self.context.fs, self.subject, self.object, dry=False)
