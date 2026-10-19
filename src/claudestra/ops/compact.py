"""What compacting a session needs that is not an action of its own (actions/compact.py): how a
transcript records a compaction, and a running session's status."""

from __future__ import annotations

from .. import portable
from ..claude_fs import ClaudeFS

BOUNDARY = b'"compact_boundary"'  # what a transcript records once it is compacted


def status(fs: ClaudeFS, sid: str) -> str | None:
    """A running session's status, as its pid file gives it (idle, busy), or None if it is not running. Claude
    Code writes the pid file before the status, so a session just started is "starting" until it reports."""
    if pid := portable.running_pid(fs.sessions, fs.proc, sid):
        rec = portable.live_pid_record(fs.sessions, fs.proc, pid)
        return (rec.get("status") if rec else None) or "starting"
    return None
