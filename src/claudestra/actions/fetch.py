"""`claudestra machine fetch`: move a stopped session from another machine to this one (ops/transfer.py). The user's alone."""

from __future__ import annotations

from pathlib import Path

from ..caller import Refused
from ..ops import preferences as prefs
from ..ops import transfer
from .base import Action
from .permissions import Kinds


class Fetch(Action):
    verb = "fetch"
    who = Kinds(frozenset({"human"}))

    def __init__(
        self, session_id: str, host: str, src: str | None = None, dest: Path | None = None, copy_memory: bool = False
    ):
        super().__init__(session_id)
        self.host, self.src, self.dest, self.copy_memory = host, src, dest, copy_memory
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
            self.copy_memory,
        )

    def _device_scope(self) -> bool:
        return self.context.trust.scope(self.object) == "device"

    def check(self) -> None:
        if self._device_scope() and prefs.device_scopes_bound(self.context.trust.config):
            raise Refused(f"{self.object} is a device scope, bound to its own machine ({prefs.UNBIND})")
        self.plan = self._fetch(dry=True)

    def describe(self) -> list[str]:
        warn = ["warning: a device scope is moving to a machine it does not organise"] if self._device_scope() else []
        return warn + self.plan.describe()

    def run(self) -> transfer.TransferPlan:
        return self._fetch(dry=False)
