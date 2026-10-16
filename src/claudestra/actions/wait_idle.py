"""`claudestra session wait`: hold until sessions are idle, or have stopped, so that a manager can brief a
staffer and wait for its turn to end, or a script can go on when the work is done. It changes nothing."""

from __future__ import annotations

import time

from ..caller import Refused
from ..ops import compact as compact_ops
from .base import ReadOnlyAction
from .wait import POLL


class WaitIdle(ReadOnlyAction):
    verb = "wait"

    def __init__(self, sessions: list, seconds: float):
        super().__init__(sessions)
        self.seconds = seconds

    def run(self) -> dict[str, str]:
        """Each session's state when it was done: idle, or stopped."""
        fs = self.context.fs
        deadline = time.monotonic() + self.seconds
        done: dict[str, str] = {}
        while True:
            for s in self.object:
                if s.id not in done:
                    st = compact_ops.status(fs, s.id)
                    if st is None or st == "idle":
                        done[s.id] = "stopped" if st is None else "idle"
            if len(done) == len(self.object):
                return done
            if time.monotonic() >= deadline:
                busy = [s.id[:8] for s in self.object if s.id not in done]
                raise Refused(f"gave up after {self.seconds:g}s; still busy: {', '.join(busy)}")
            time.sleep(POLL)
