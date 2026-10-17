"""`claudestra session list`: every session on this machine. `staff list` lists the staff on every machine."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..session import Session
from .base import ReadOnlyAction


@dataclass
class Listing:
    sessions: list[Session]  # staffers first, then running ones, then by last activity
    total: int  # every session on this machine
    running: int
    unwritten: list = field(default_factory=list)  # runs whose session has no transcript yet (model.Run)


class List(ReadOnlyAction):
    verb = "list"

    def run(self) -> Listing:
        c = self.context
        m = c.model
        records = sorted(
            m.sessions.values(),
            key=lambda s: (s.staff_file is None, not s.runs, -s.mtime),
        )
        unwritten = [r for r in m.runs if r.session_id not in m.sessions]
        return Listing([Session(r.session_id) for r in records], len(m.sessions), len(m.runs), unwritten)
