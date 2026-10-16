"""`claudestra preferences`: the user's preferences, read by anyone and set by the user alone (DESIGN.md §6.6)."""

from __future__ import annotations

from ..ops import preferences as prefs
from .base import Action, ReadOnlyAction
from .permissions import Kinds


class ShowPreferences(ReadOnlyAction):
    verb = "preferences"

    def run(self) -> dict[str, str | None]:
        return prefs.load(self.context.trust.config)


class SetPreference(Action):
    verb = "preferences"
    who = Kinds(frozenset({"human"}))
    needs: list[str] = []
    reversible = True

    def __init__(self, key: str, value: str):
        super().__init__(key)
        self.value = value
        self.before: str | None = None

    def check(self) -> None:
        prefs.check(self.object, self.value)

    def describe(self) -> list[str]:
        meaning = prefs.PREFERENCES[self.object].choices[self.value]
        return [f"{prefs.path(self.context.trust.config)}: {self.object} = {self.value} ({meaning})"]

    def run(self) -> None:
        p = prefs.path(self.context.trust.config)
        self.before = p.read_text() if p.is_file() else None
        prefs.save(self.context.trust.config, self.object, self.value)

    def undo(self) -> None:
        p = prefs.path(self.context.trust.config)
        if self.before is None:
            p.unlink()
        else:
            p.write_text(self.before)
