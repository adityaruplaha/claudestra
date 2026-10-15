"""`claudestra trust grant`: give a staffer a scope. The user's alone."""

from __future__ import annotations

from ..caller import Refused
from ..claude_fs import UUID
from ..ops import trust_file
from ..trust import SCOPES
from .base import Action
from .permissions import Kinds


class TrustGrant(Action):
    verb = "trust grant"
    who = Kinds(frozenset({"human"}))
    needs: list[str] = []
    reversible = True

    def __init__(self, session_id: str, scope: str):
        super().__init__(session_id)
        self.scope = scope
        self.before: str | None = None

    def check(self) -> None:
        c, sid = self.context, self.object
        if not UUID.match(sid):
            raise Refused(f"{sid!r} is not a full session ID")
        if self.scope not in SCOPES:
            raise Refused(f"a scope is {' or '.join(SCOPES)}, not {self.scope!r}")
        if c.trust.staff_file(sid) is None:
            raise Refused(f"{sid} is not on the staff; a scope is a staffer's, so hire it first")
        if c.trust.scopes.get(sid) == self.scope:
            raise Refused(f"{sid} already has {self.scope} scope")

    def describe(self) -> list[str]:
        sid = self.object
        was = self.context.trust.scopes.get(sid)
        return [
            f"trust.yaml: {sid} ({self.context.name_of(sid) or '-'}) gets {self.scope} scope"
            + (f", was {was}" if was else "")
        ]

    def run(self) -> None:
        c = self.context
        self.before = trust_file.change(
            c.trust.trust_file, lambda raw: raw["sessions"].__setitem__(self.object, {"scope": self.scope}), c.name_of
        )

    def undo(self) -> None:
        trust_file.restore(self.context.trust.trust_file, self.before)
        self.context.refresh()
