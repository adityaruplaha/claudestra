"""A wait: a reading action that holds until a condition is true, or refuses when it times out.
Workflows use it between steps (Compact waits for a session to come up idle)."""

from __future__ import annotations

import time
from collections.abc import Callable

from ..caller import Refused
from .base import ReadOnlyAction

POLL = 0.5


class Wait(ReadOnlyAction):
    verb = "wait"

    def __init__(self, what: str, condition: Callable[[], bool], seconds: float):
        super().__init__()
        self.what, self.condition, self.seconds = what, condition, seconds

    def describe(self) -> list[str]:
        return [f"wait up to {self.seconds:g}s for {self.what}"]

    def run(self) -> None:
        deadline = time.monotonic() + self.seconds
        while time.monotonic() < deadline:
            if self.condition():
                return
            time.sleep(POLL)
        raise Refused(f"gave up waiting {self.seconds:g}s for {self.what}")
