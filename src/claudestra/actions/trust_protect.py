"""`claudestra trust protect add|remove`: a machine's protected folders, whose sessions may not leave
them. The user's alone."""

from __future__ import annotations

from pathlib import Path

from ..caller import Refused
from ..ops import trust_file
from ..trust import tilde
from .base import Action
from .permissions import Kinds


class TrustProtect(Action):
    verb = "trust protect"
    who = Kinds(frozenset({"human"}))
    needs: list[str] = []
    reversible = True

    def __init__(self, folder: Path, add: bool, host: str | None = None):
        super().__init__(folder)
        self.add, self.host = add, host
        self.before: str | None = None
        self.written = ""

    def check(self) -> None:
        c = self.context
        host = self.host or c.machine.hostname
        mc = c.trust.machines.get(host.lower())
        if mc is None:
            raise Refused(f"{host} is not under machines in trust.yaml; add it with `claudestra trust machine add`")
        self.written = tilde(Path(self.object), mc.home)  # written with ~ for that machine's home
        listed = c.trust.protected_raw.get(mc.hostname, [])
        if self.add and self.written in listed:
            raise Refused(f"{self.written} is already protected on {host}")
        if not self.add and self.written not in listed:
            raise Refused(f"{self.written} is not protected on {host}")

    def describe(self) -> list[str]:
        host = self.host or self.context.machine.hostname
        return [f"trust.yaml: {self.written} {'is' if self.add else 'is no longer'} protected on {host}"]

    def run(self) -> None:
        c = self.context
        host = (self.host or c.machine.hostname).lower()

        def edit(raw: dict) -> None:
            mc = next(v for k, v in raw["machines"].items() if str(k).lower() == host)
            listed = mc.setdefault("protected", [])
            if self.add:
                listed.append(self.written)
            else:
                listed.remove(self.written)

        self.before = trust_file.change(c.trust.trust_file, edit, c.name_of)

    def undo(self) -> None:
        trust_file.restore(self.context.trust.trust_file, self.before)
        self.context.refresh()
