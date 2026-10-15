"""`claudestra permissions`: who may take each action, as the actions themselves declare it."""

from __future__ import annotations

from .base import ReadOnlyAction
from .permissions import RELATIONS, Rule, matrix


class Permissions(ReadOnlyAction):
    verb = "permissions"

    def run(self) -> tuple[list[str], dict[str, Rule]]:
        """(the relations, in order; each verb's rule, permissions.Relations, Kinds or Anyone)."""
        return RELATIONS, matrix()
