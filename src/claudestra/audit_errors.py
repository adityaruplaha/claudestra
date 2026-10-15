"""What `claudestra audit` finds: one class per kind of problem, each with what it is about and why.

An error that claudestra can fix safely says how: `fix()` returns the action that fixes it, which is
authorized like any other, and `audit --fix` takes those (actions/fix_audit.py). The rest are reported
for the user to settle, since fixing them means a judgement (which copy of a fork is the session, which
of two stores owns a file) that claudestra does not make.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass
class AuditError:
    report: ClassVar[str]  # the audit report that finds it
    subject: str  # what it is about: a session ID, a path, a slug
    detail: str

    def fix(self):
        """The action that fixes it, or None where fixing it needs the user's judgement."""
        return None


class Fork(AuditError):
    report = "forks"  # one history copied into several transcripts


class SubagentCopy(AuditError):
    report = "subagents"  # a subagent transcript whose records end under another session


class Symlink(AuditError):
    report = "links"  # a store holding a symlink, possibly dangling


class BrokenRedirect(AuditError):
    report = "redirects"  # a workspace folder's .session-aliases pointing nowhere useful


class TwoHomes(AuditError):
    report = "two-homes"  # one session filed under two slugs


class ManyRuns(AuditError):
    report = "runs"  # one session hosted by several live processes


class Orphan(AuditError):
    report = "orphans"  # a store or folder with no transcript behind it


class Stale(AuditError):
    report = "stale"  # a pid file, key or socket of a process that is gone


class OrphanJob(AuditError):
    report = "jobs"  # a background job whose session has no transcript here


class SharedSlug(AuditError):
    report = "slugs"  # several folders filing their sessions under one slug


class StaleConfig(AuditError):
    report = "config"  # a ~/.claude.json entry for a folder or session that is gone


class NameMismatch(AuditError):
    """A staffer's staff file name is not its session's title, as after a /rename typed inside the session."""

    report = "names"

    def fix(self):
        from .caller import Refused
        from .context import Context

        try:
            return Context.current().staffer(self.subject).fix_name()
        except Refused:
            return None  # off the staff since the audit read it
