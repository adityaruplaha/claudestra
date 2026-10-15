"""`claudestra trust show`: trust.yaml as claudestra reads it, each session with its current name."""

from __future__ import annotations

from ..ops import trust_file
from .base import ReadOnlyAction


class TrustShow(ReadOnlyAction):
    verb = "trust show"

    def run(self) -> str:
        """The file as `claudestra trust` would write it, with names current."""
        c = self.context
        raw = trust_file.read(c.trust.trust_file)
        for mc in raw["machines"].values():
            for k in ("ssh", "autostart", "protected"):
                if not mc.get(k):
                    mc.pop(k, None)
        return trust_file.emit(raw, c.name_of)
