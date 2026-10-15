"""`claudestra trust revoke`: take a session's scope away. The user's alone."""

from __future__ import annotations

from ..caller import Refused
from ..ops import trust_file
from .base import Action
from .permissions import Kinds


class TrustRevoke(Action):
    verb = "trust revoke"
    who = Kinds(frozenset({"human"}))
    needs: list[str] = []
    reversible = True

    def __init__(self, session_id: str):
        super().__init__(session_id)
        self.before: str | None = None

    def check(self) -> None:
        if self.context.trust.scopes.get(self.object) is None:
            raise Refused(f"{self.object} has no scope to revoke")

    def describe(self) -> list[str]:
        sid = self.object
        return [
            f"trust.yaml: {sid} ({self.context.name_of(sid) or '-'}) loses its {self.context.trust.scopes.get(sid)} scope"
        ]

    def run(self) -> None:
        c = self.context
        self.before = trust_file.change(c.trust.trust_file, lambda raw: raw["sessions"].pop(self.object), c.name_of)

    def undo(self) -> None:
        trust_file.restore(self.context.trust.trust_file, self.before)
        self.context.refresh()
