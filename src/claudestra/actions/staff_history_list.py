"""`claudestra staff history list`: a staffer's history, oldest first. The sessions it had before, with when and
why each was rotated, come from its staff file, which every machine sees; its hires, dismissals, renames and
descriptions under any of its sessions come from claudestra's log, which each machine keeps for itself, so
those are what happened on this machine. Anyone's."""

from __future__ import annotations

from .base import ReadOnlyAction
from .log import Log

EVENTS = ("hire", "dismiss", "rename", "describe", "fix-name", "staff history add")


class StaffHistoryList(ReadOnlyAction):
    verb = "staff history list"

    def run(self) -> list[dict]:
        sf = self.context.staffer(self.object).staff_file
        sessions = {sf.session, *sf.past_sessions}
        rows = [
            {"at": h.get("rotated"), "event": "rotated", "session": h["session"], "detail": h.get("reason")}
            for h in sf.history
        ]
        rows += [
            {"at": e.get("at"), "event": e["action"], "session": e["subject"], "detail": e.get("detail") or None}
            for e in Log(None, last=10**9).run()
            if e.get("subject") in sessions and e.get("action") in EVENTS
        ]
        return sorted(rows, key=lambda r: r["at"] or "")
