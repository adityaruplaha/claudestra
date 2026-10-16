"""`claudestra install completion`: shell completion for `claudestra` and `clost` (ops/completion.py).

It only adds completion to the user's own shell, so anyone may run it, a session or the plugin included."""

from __future__ import annotations

from ..caller import Refused
from ..ops import completion
from .base import Action
from .permissions import Anyone


class InstallCompletion(Action):
    verb = "completion"
    who = Anyone("it only adds completion to the user's shell")
    needs: list[str] = []

    def __init__(self, shell: str | None = None):
        super().__init__(shell or completion.user_shell())

    def check(self) -> None:
        if self.object not in completion.SHELLS:
            raise Refused(
                f"no completion for {self.object or 'this shell'}; name one of {', '.join(completion.SHELLS)}"
            )

    def describe(self) -> list[str]:
        return completion.install(self.object, self.context.fs.home, True)

    def run(self) -> list[str]:
        return completion.install(self.object, self.context.fs.home, False)
