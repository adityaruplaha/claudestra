"""`claudestra session rename`: rename a stopped session as `/rename` does inside one.

A running staffer in claudestra's tmux is renamed by typing `/rename` into its window instead
(runners/tmux.py): a running Claude Code re-appends its own title records, and the last one wins.

`/rename` appends a `custom-title` and an `agent-name` record carrying the new name and writes
`<id>/custom-title.json`; the name a session is listed and messaged by comes from these. A staffer's
staff file `name` follows, so claudestra and the session agree.
"""

from __future__ import annotations

import json

from ..caller import Caller, Refused
from ..claude_fs import ClaudeFS
from ..model import SessionRecord
from ..portable import atomic_write_text
from ..trust import Trust, set_staff_name
from .common import log, refuse_if_running

MAX_NAME = 120


def check_name(name: str) -> str:
    n = name.strip()
    if not n or "\n" in n or len(n) > MAX_NAME:
        raise Refused(f"a name is one line of 1 to {MAX_NAME} characters")
    return n


def check(trust: Trust, s: SessionRecord, name: str) -> str:
    """What every rename checks, running or not: the name, one home, and no other staffer of that name.
    Who may rename is the action's to decide (actions/rename.py)."""
    name = check_name(name)
    if len(s.homes) != 1:
        raise Refused(f"{s.session_id} is filed under {len(s.homes)} slugs; settle that first")
    if clash := next((a for a in trust.staff if a.name == name and a.session != s.session_id), None):
        raise Refused(f"the staffer {clash.session} is already named {name!r}")
    return name


def write(fs: ClaudeFS, caller: Caller, s: SessionRecord, name: str) -> None:
    refuse_if_running(fs, s)  # again: the user may have resumed it while the plan was shown
    sid = s.session_id
    t = fs.transcript(s.homes[0], sid)
    with t.open("rb+") as fh:  # a transcript cut by a crash may lack its last newline
        fh.seek(0, 2)
        if fh.tell():
            fh.seek(-1, 2)
            if fh.read(1) != b"\n":
                fh.write(b"\n")
        for rec in (
            {"type": "custom-title", "customTitle": name, "sessionId": sid},
            {"type": "agent-name", "agentName": name, "sessionId": sid},
        ):
            fh.write((json.dumps(rec, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
    (t.parent / sid).mkdir(exist_ok=True)
    atomic_write_text(
        t.parent / sid / "custom-title.json",
        json.dumps({"customTitle": name}, ensure_ascii=False, separators=(",", ":")),
    )
    if s.staff_file:
        set_staff_name(s.staff_file, name)
    log(caller, "rename", sid, f"{s.name!r} -> {name!r}")
