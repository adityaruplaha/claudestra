"""`claudestra trash purge`: delete trash entries for good, the ones named or every one the filters pass: older
than some days, or left behind when their session moved to another machine, to any or to the ones given. The
user's alone."""

from __future__ import annotations

from pathlib import Path

from ..caller import Refused
from ..ops import trash as trash_ops
from .base import Action
from .permissions import Kinds


class Purge(Action):
    verb = "purge"
    who = Kinds(frozenset({"human"}))
    needs: list[str] = []

    def __init__(self, choice: trash_ops.Choice):
        super().__init__()
        self.choice = choice
        self.doomed: list[Path] = []

    def check(self) -> None:
        known = {h.lower() for h in self.context.trust.machines}
        if unknown := [h for h in self.choice.moved_to if h.lower() not in known]:
            raise Refused(f"--moved-to: trust.yaml names no machine {', '.join(unknown)}")
        self.doomed = trash_ops.purgeable(self.context.fs, self.choice)

    def describe(self) -> list[str]:
        manifests = dict(trash_ops.entries(self.context.fs))
        out = []
        for e in self.doomed:
            mf = manifests.get(e)
            title = (mf or {}).get("title") or ("-" if mf else "(no manifest)")
            reason = trash_ops.why(mf)
            out.append(f"delete {e.name}  {title}" + (f"  ({reason})" if reason else ""))
        return out

    def run(self) -> list[str]:
        return trash_ops.purge(self.context.fs, self.subject, self.doomed)
