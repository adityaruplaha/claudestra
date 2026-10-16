"""`claudestra uninstall`: take out what claudestra put on this machine outside its own package, so that
removing it leaves nothing broken behind: the guard (whose hook would otherwise name a Python that is gone),
shell completion, and the login unit. The user's alone, since it takes protection away.

It keeps the config folder, which is the user's record of their staff and may be shared with other
machines, and Remote Control, which is a setting of the user's own; and it says how to remove the plugin,
which would otherwise put the guard back when the next session starts, and the CLI itself.
"""

from __future__ import annotations

from ..ops import completion, guard, unit
from .base import Action
from .permissions import Kinds


class Uninstall(Action):
    verb = "uninstall"
    who = Kinds(frozenset({"human"}))
    needs: list[str] = []

    def _plan(self, dry: bool) -> list[str]:
        c = self.context
        return [
            *unit.uninstall(dry),
            *guard.uninstall(c.fs, c.trust.config, dry),
            *completion.uninstall(c.fs.home, dry),
        ]

    def describe(self) -> list[str]:
        c = self.context
        return [
            *(self._plan(True) or ["nothing of claudestra's is installed outside its package"]),
            f"kept: the config folder, {c.trust.config}, and Remote Control in Claude Code's settings",
        ]

    def run(self) -> list[str]:
        return [
            *self._plan(False),
            "now disable the claudestra plugin (`/plugin`), or it puts the guard back when the next session starts,",
            "and remove the CLI with `uv tool uninstall claudestra`",
        ]
