"""`claudestra open-items get`: one open item in full, found by its ULID or a unique ending of it. Anyone's."""

from __future__ import annotations

from ..ops import open_items as items_ops
from .base import ReadOnlyAction


class OpenItemGet(ReadOnlyAction):
    verb = "open-items get"

    def __init__(self, ulid: str):
        super().__init__(ulid)

    def run(self) -> tuple[str, dict]:
        return items_ops.find(self.context.trust.config, self.object)
