"""How permission is worked out (DESIGN.md §6.1). Each action declares who may take it, in its own file: its
`who`, one rule: `Relations` (the subject's relations to the session it acts on), `ToFolder` (for
hiring), `Kinds` (the subject kinds, for an action on anything else) or `Anyone`. This module says what
the relations are, works one out (`relation`, from the same code that says who a staffer answers to,
`Trust.managers_over`), and refuses with the reason. Whatever is the user's alone is refused in restricted mode,
whoever the subject is taken to be, since a Claude session may be driving the terminal. `matrix()`
collects every action's rule, for `claudestra permissions`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..caller import Caller, Refused, transcript_problem
from ..context import Context
from ..portable import given_folder

# The subject's relation to a session.
USER = "user"  # the subject is the user, and nothing in the chain is Claude
SELF = "self"  # the session is the subject's own
MANAGER = "manager"  # a folder scope, over a specialist it manages
D_MANAGER = "device over a manager"  # a device scope, over a folder-scope staffer
D_UNMANAGED = "device over an unmanaged specialist"  # a device scope, over a specialist no manager holds
D_MANAGED = "device over a managed specialist"  # a device scope, over a specialist under a manager
D_DEVICE = "device over a device scope"  # a device scope, over another device scope
D_OTHER = "device over a session not on the staff"
LOGIN_AUTOSTART = "the login unit, over an autostart staffer"
NONE = "none"


def relation(subject: Caller, session) -> str:
    """The subject's relation to the session (a claudestra.session.Session)."""
    c = Context.current()
    if subject.kind == "human":
        return USER if not c.restricted else NONE
    if subject.session == session.id:
        return SELF
    if not session.on_staff:
        return D_OTHER if subject.kind == "device" else NONE
    st = c.staffer(session.id)
    sf, scope = st.staff_file, st.scope
    if subject.kind == "login":
        return LOGIN_AUTOSTART if st.autostart else NONE
    if subject.kind == "device":
        if scope == "folder":
            return D_MANAGER
        if scope == "device":
            return D_DEVICE
        return D_MANAGED if st.managers else D_UNMANAGED
    # A folder scope's own specialists: those it manages, checked against the folder its process proves.
    if (
        subject.kind == "folder"
        and scope is None
        and subject.folder is not None
        and sf.folder is not None
        and any(m.id == subject.session for m in st.managers)
        and sf.folder.is_relative_to(subject.folder)
        and not transcript_problem(c.fs, c.machine.hostname, sf.session, sf.folder)
    ):
        return MANAGER
    return NONE


def relation_to_folder(subject: Caller, folder: Path, sid: str) -> str:
    """The subject's relation to a folder session `sid` would work in, for hiring it there: the relation
    it would have to the specialist hired."""
    folder = given_folder(folder)  # however it was reached, `..` never counts as inside
    c = Context.current()
    if subject.kind == "human":
        return USER if not c.restricted else NONE
    if subject.session == sid:
        return SELF
    managers = c.trust.managers_of(folder, sid)
    if subject.kind == "device":
        return D_MANAGED if managers else D_UNMANAGED
    if (
        subject.kind == "folder"
        and subject.folder is not None
        and folder.is_relative_to(subject.folder)
        and any(m.session == subject.session for m in managers)
    ):
        return MANAGER
    return NONE


def require_on_session(verb: str, subject: Caller, session, allowed: frozenset[str], rel: str | None = None) -> None:
    """Refuse unless the subject's relation to the session (worked out here unless given) is one of
    `allowed`, saying why not."""
    rel = rel or relation(subject, session)
    if rel in allowed:
        return
    name = Context.current().name_of(session.id) or session.id
    if rel == SELF:
        raise Refused(f"a session may not {verb} itself")
    if rel == NONE and subject.kind == "human":
        raise Refused(f"{verb} needs the user at a terminal, and Claude is in the process chain (restricted mode)")
    may = ", ".join(sorted(allowed))
    raise Refused(
        f"{subject.describe()} may not {verb} {name!r}: its relation to it is {rel}; {verb} needs one of: {may}"
    )


def require_kind(verb: str, subject: Caller, kinds: frozenset[str]) -> None:
    """Refuse unless the subject's kind is one of `kinds`, and anything the user's alone in restricted mode."""
    if subject.kind not in kinds:
        who = " or ".join(
            {"human": "the user at a terminal", "device": "a device-scope session"}[k] for k in sorted(kinds)
        )
        raise Refused(f"{verb} is for {who}; the caller is {subject.describe()}")
    if kinds == {"human"} and Context.current().restricted:
        raise Refused(f"{verb} is the user's alone, and Claude is in the process chain (restricted mode)")


RELATIONS = [USER, MANAGER, D_MANAGER, D_UNMANAGED, D_MANAGED, D_DEVICE, D_OTHER, LOGIN_AUTOSTART]


# --- the rules an action declares, as its `who` ----------------------------------------------------


class Rule(Protocol):
    def require(self, action) -> None:
        """Refuse, saying why, unless the action's subject may take it."""


@dataclass(frozen=True)
class Relations:
    """An action on a session: the subject's relations to it that may take it."""

    allowed: frozenset[str]

    def require(self, action) -> None:
        require_on_session(action.verb, action.subject, action.object, self.allowed)


@dataclass(frozen=True)
class ToFolder(Relations):
    """Hiring: the relation the subject would have to the specialist hired, worked out from the folder it
    will work in (`action.folder_here`), since the session is not on the staff yet."""

    def require(self, action) -> None:
        rel = relation_to_folder(action.subject, action.folder_here, action.object.id)
        require_on_session(action.verb, action.subject, action.object, self.allowed, rel)


@dataclass(frozen=True)
class Kinds:
    """An action on anything else: the subject kinds that may take it; the user's alone is refused in restricted
    mode."""

    kinds: frozenset[str]

    def require(self, action) -> None:
        require_kind(action.verb, action.subject, self.kinds)


@dataclass(frozen=True)
class Anyone:
    """No refusal of its own: a reading action, or one whose parts are each authorized as their own verb."""

    note: str = "anyone"

    def require(self, action) -> None:
        return None


def matrix() -> dict[str, Rule]:
    """Every action that changes something, by verb, with the rule it declares."""
    from . import base, load_all

    load_all()
    found: dict[str, Rule] = {}

    def walk(cls):
        for sub in cls.__subclasses__():
            if (
                "verb" in sub.__dict__
                and sub.changes
                and sub.__module__.startswith("claudestra.actions.")
                and sub is not base.Transaction
            ):
                found[sub.verb] = sub.who
            walk(sub)

    walk(base.Action)
    return dict(sorted(found.items()))
