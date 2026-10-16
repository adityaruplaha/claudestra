"""`claudestra log`: claudestra's own record of what it did, newest last: who did what to which session, and
when. Every changing action writes a line to it (ops/common.log); this reads them back."""

from __future__ import annotations

import json

from ..ops.common import STATE_DIR
from .base import ReadOnlyAction


class Log(ReadOnlyAction):
    verb = "log"

    def __init__(self, session_id: str | None = None, last: int = 50):
        super().__init__(session_id)
        self.last = last

    def run(self) -> list[dict]:
        try:
            lines = (STATE_DIR / "log").read_text().splitlines()
        except OSError:
            return []
        entries = []
        for line in lines:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and (self.object is None or e.get("subject") == self.object):
                entries.append(e)
        return entries[-self.last :]
