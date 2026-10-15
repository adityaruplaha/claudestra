"""What compacting a session needs that is not an action of its own (actions/compact.py): how a
transcript records a compaction, and a running session's status."""

from __future__ import annotations

from .. import portable
from ..claude_fs import ClaudeFS

BOUNDARY = b'"compact_boundary"'  # what a transcript records once it is compacted


def status(fs: ClaudeFS, sid: str) -> str | None:
    if pid := portable.running_pid(fs.sessions, fs.proc, sid):
        rec = portable.live_pid_record(fs.sessions, fs.proc, pid)
        return rec.get("status") if rec else None
    return None
