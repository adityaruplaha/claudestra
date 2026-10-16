"""`claudestra trust machine add|remove`: the machines trust.yaml describes. The user's alone.

This machine's home and derived machine ID are worked out here; another machine's are given, from
`claudestra trust machine add` run there, since its derived ID cannot be computed from here."""

from __future__ import annotations

from pathlib import Path

from .. import portable
from ..caller import Refused
from ..ops import trust_file
from .base import Action
from .permissions import Kinds


class TrustMachine(Action):
    verb = "trust machine"
    who = Kinds(frozenset({"human"}))
    needs: list[str] = []
    reversible = True
    machine_known = False  # it is how a machine gets into trust.yaml, or out of it when its ID has changed

    def __init__(
        self,
        add: bool,
        host: str | None = None,
        home: Path | None = None,
        machine_id: str | None = None,
        ssh: str | None = None,
    ):
        super().__init__(host)
        self.add, self.home, self.machine_id, self.ssh = add, home, machine_id, ssh
        self.before: str | None = None

    @property
    def host(self) -> str:
        return self.object or self.context.machine.hostname

    def check(self) -> None:
        c = self.context
        here = self.host.lower() == c.machine.hostname.lower()
        known = c.trust.machines.get(self.host.lower())
        if not self.add:
            if known is None:
                raise Refused(f"{self.host} is not under machines in trust.yaml")
            return
        if known is not None:
            raise Refused(f"{self.host} is already under machines; remove it first to describe it again")
        if here:
            self.home = self.home or c.fs.home
            self.machine_id = self.machine_id or portable.machine_id()
            if self.machine_id != portable.machine_id():
                raise Refused("this machine's derived ID is worked out here; leave --machine-id out")
        elif self.home is None or self.machine_id is None:
            raise Refused(
                f"give {self.host}'s --home and --machine-id, as `claudestra trust machine add` prints them there"
            )

    def describe(self) -> list[str]:
        if not self.add:
            return [f"trust.yaml: {self.host} is no longer described"]
        ssh = f", accepting connections at {self.ssh}" if self.ssh else ", accepting no connections"
        return [f"trust.yaml: {self.host}, home {self.home}, machine ID {self.machine_id}{ssh}"]

    def run(self) -> None:
        c = self.context

        def edit(raw: dict) -> None:
            if not self.add:
                key = next(k for k in raw["machines"] if str(k).lower() == self.host.lower())
                del raw["machines"][key]
                return
            entry = {"home": str(self.home), "machine_id": self.machine_id}
            if self.ssh:
                entry["ssh"] = self.ssh
            raw["machines"][self.host] = entry

        self.before = trust_file.change(c.trust.trust_file, edit, c.name_of)

    def undo(self) -> None:
        trust_file.restore(self.context.trust.trust_file, self.before)
        self.context.refresh()
