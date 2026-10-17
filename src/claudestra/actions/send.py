"""`claudestra machine send`: move a stopped session from this machine to another (ops/transfer.py). The user's alone,
and the user confirms by typing the session's full ID, since what a transcript read is not visible from its
folder (DESIGN.md §6.3)."""

from __future__ import annotations

from pathlib import Path

from ..caller import Refused
from ..ops import preferences as prefs
from ..ops import transfer
from .base import SessionAction
from .permissions import USER, Relations


class Send(SessionAction):
    verb = "send"
    who = Relations(frozenset({USER}))

    def __init__(self, session, host: str, dest: str | None = None, src: Path | None = None, copy_memory: bool = False):
        super().__init__(session)
        self.host, self.dest, self.src, self.copy_memory = host, dest, src, copy_memory
        self.plan: transfer.TransferPlan | None = None

    def transport(self) -> transfer.Transport:
        conf = self.context.trust.machines.get(self.host.lower())
        if conf is None:
            raise Refused(f"{self.host} is not under machines in trust.yaml")
        return transfer.SSHTransport(conf)

    def _send(self, dry: bool):
        c, r = self.context, self.session.record
        if r is None:
            raise Refused(f"{self.session.id} has no transcript on this machine")
        return transfer.send(
            c.fs,
            c.machine.hostname,
            c.trust.machines,
            c.trust,
            self.subject,
            r,
            self.transport(),
            self.dest,
            self.src,
            dry,
            lambda _sid: True,
            self.copy_memory,
        )

    def _device_scope(self) -> bool:
        return self.context.trust.scope(self.session.id) == "device"

    def check(self) -> None:
        if self._device_scope() and prefs.device_scopes_bound(self.context.trust.config):
            raise Refused(f"{self.session.id} is a device scope, bound to its own machine ({prefs.UNBIND})")
        self.plan = self._send(dry=True)

    def describe(self) -> list[str]:
        warn = ["warning: a device scope is moving to a machine it does not organise"] if self._device_scope() else []
        return warn + self.plan.describe()

    def run(self) -> transfer.TransferPlan:
        return self._send(dry=False)
