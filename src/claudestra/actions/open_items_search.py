"""`claudestra open-items search`: the open items whose title, description or where holds the text, ignoring
case, in the project `list` would show. Anyone's."""

from __future__ import annotations

from .base import ReadOnlyAction
from .open_items_list import OpenItemsList


class OpenItemsSearch(ReadOnlyAction):
    verb = "open-items search"

    def __init__(self, text: str, session: str | None = None, everything: bool = False):
        super().__init__(text)
        self.scope = OpenItemsList(session, everything)

    def run(self) -> list[tuple[str, dict]]:
        want = self.object.lower()
        return [
            (o, i)
            for o, i in self.scope.run()
            if any(want in (i.get(k) or "").lower() for k in ("title", "description", "where"))
        ]
