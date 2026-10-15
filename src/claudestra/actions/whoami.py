"""`claudestra whoami`: who is calling, what it runs under, and what it may do."""

from __future__ import annotations

from dataclasses import dataclass

from ..caller import Caller, Refused
from ..proctree import ClaudeProc
from ..session import Session
from .base import ReadOnlyAction
from .permissions import matrix, require_on_session

VERBS = ("start", "stop", "move", "rename", "type")


@dataclass
class Identity:
    subject: Caller
    restricted: bool  # a Claude process is in the chain, so what is the user's alone is refused
    chain: list[ClaudeProc]  # every Claude process in the chain, nearest first
    managed_by: str | None  # for a staffer: who it answers to
    may: dict[str, list[str]]  # per verb, the staffers it may take it on


class Whoami(ReadOnlyAction):
    verb = "whoami"

    def run(self) -> Identity:
        c = self.context
        subject = c.subject
        me = c.trust.staff_file(subject.session)
        rules = matrix()
        may = {
            v: [a.name for a in c.trust.staff if _may(v, rules[v].allowed, subject, Session(a.session))] for v in VERBS
        }
        return Identity(subject, c.restricted, c.chain, c.trust.managed_by(me) if me else None, may)


def _may(verb: str, allowed: frozenset[str], subject: Caller, session: Session) -> bool:
    try:
        require_on_session(verb, subject, session, allowed)
    except Refused:
        return False
    return True
