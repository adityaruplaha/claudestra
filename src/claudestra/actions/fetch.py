"""`claudestra fetch`: move a stopped session from another machine to this one (ops/transfer.py). The user's alone."""

from __future__ import annotations

from pathlib import Path

from ..caller import Refused
from ..ops import transfer
from .base import Action
from .permissions import Kinds


class Fetch(Action):
    verb = "fetch"
    who = Kinds(frozenset({"human"}))

    def __init__(self, session_id: str, host: str, src: str | None = None, dest: Path | None = None):
        super().__init__(session_id)
        self.host, self.src, self.dest = host, src, dest
        self.plan: transfer.TransferPlan | None = None

    def _fetch(self, dry: bool):
        c = self.context
        conf = c.trust.machines.get(self.host.lower())
        if conf is None:
            raise Refused(f"{self.host} is not under machines in trust.yaml")
        sf = c.trust.staff_file(self.object)
        return transfer.fetch(
            c.fs,
            c.machine.hostname,
            c.trust.machines,
            c.trust,
            self.subject,
            self.object,
            transfer.SSHTransport(conf),
            self.src,
            self.dest,
            sf.folders if sf else {},
            dry,
        )

    def check(self) -> None:
        self.plan = self._fetch(dry=True)

    def describe(self) -> list[str]:
        return self.plan.describe()

    def run(self) -> transfer.TransferPlan:
        return self._fetch(dry=False)
