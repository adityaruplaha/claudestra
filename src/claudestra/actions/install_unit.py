"""`claudestra install login-unit`: the login unit that starts this machine's autostart staffers. The user's alone."""

from __future__ import annotations

from ..ops import unit as unit_ops
from .base import Action
from .permissions import Kinds


class InstallUnit(Action):
    verb = "install"
    who = Kinds(frozenset({"human"}))
    needs: list[str] = []

    def __init__(self):
        super().__init__()
        self.would: list[str] = []

    def check(self) -> None:
        self.would = unit_ops.install(True)

    def describe(self) -> list[str]:
        return self.would

    def run(self) -> list[str]:
        return unit_ops.install(False)[len(self.would) - 1 :]
