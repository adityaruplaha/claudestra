"""`claudestra install guard`: the deny rules and the hook that keep sessions out of claudestra's config.

It only adds protection, so anyone may run it, a session or the plugin's `SessionStart` hook included, and it
asks nothing of the caller: no subject is identified and no preamble is run, since a config with errors or
a machine trust.yaml does not yet describe needs the guard as much as any. Nothing takes it away.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..caller import Refused
from ..ops import guard as guard_ops
from ..ops.common import locked
from .base import Action
from .permissions import Anyone


class InstallGuard(Action):
    verb = "guard"
    who = Anyone("it only adds protection")
    needs: list[str] = []

    def describe(self) -> list[str]:
        return guard_ops.install(self.context.fs, self.context.trust.config, True)

    def run(self) -> list[str]:
        """The plan was shown before it ran, so it says only that it is done."""
        guard_ops.install(self.context.fs, self.context.trust.config, False)
        return ["the guard is in place"]

    def perform(self, go_ahead: Callable[[list[str]], bool] = lambda plan: True) -> Any:
        plan = self.describe()
        if not go_ahead(plan):
            return None
        with locked():
            if self.describe() != plan:
                raise Refused("something changed while you were deciding; run it again to see the new plan")
            return self.run()
