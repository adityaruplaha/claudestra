"""`claudestra ls`: the sessions on this machine, and staffers whose session lives on another."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..session import Session
from ..trust import StaffFile
from .base import ReadOnlyAction


@dataclass
class Listing:
    sessions: list[Session]  # staffers first, then running ones, then by last activity
    elsewhere: list[StaffFile]  # staffers with a folder here whose session is not on this machine
    total: int  # every session on this machine
    running: int
    unwritten: list = field(default_factory=list)  # runs whose session has no transcript yet (model.Run)


class List(ReadOnlyAction):
    verb = "list"

    def __init__(self, show_all: bool = False):
        super().__init__()
        self.show_all = show_all

    def run(self) -> Listing:
        c = self.context
        m = c.model
        records = sorted(
            (s for s in m.sessions.values() if self.show_all or s.runs or s.staff_file),
            key=lambda s: (s.staff_file is None, not s.runs, -s.mtime),
        )
        elsewhere = [a for a in c.trust.staff if a.folder and a.session not in m.sessions]
        unwritten = [r for r in m.runs if r.session_id not in m.sessions]
        return Listing([Session(r.session_id) for r in records], elsewhere, len(m.sessions), len(m.runs), unwritten)
