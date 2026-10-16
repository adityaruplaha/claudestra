"""Actions: a subject, a verb and an object (DESIGN.md §5).

The subject is who is calling, as the context identifies it from the process chain; an action never
takes one as an argument. The verb is the action's class. The object is what it acts on: a session,
a trash entry, a machine, or nothing.

Every action answers four questions, in order: `check()` (is it well formed and possible now?),
`authorize()` (may this subject do it?), `describe()` (what will happen?) and `run()` (do it).
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any, ClassVar

from ..caller import Caller, Refused
from ..context import Context
from ..ops.common import locked
from .permissions import Anyone, Rule

# The doctor checks an action that changes session files depends on.
FS_CHECKS = ["pid-files", "proc-start", "slug-rule", "transcript-ids"]


class Action:
    verb: ClassVar[str]
    who: ClassVar[Rule]  # who may take it (permissions.py), declared by every action
    reversible: ClassVar[bool] = False  # if so, it overrides undo()
    changes: ClassVar[bool] = True  # False: no preamble, no confirmation, no lock (ReadOnlyAction)
    locks: ClassVar[bool] = True  # False: all of perform but the lock (Attach, whose process becomes tmux)

    def __init_subclass__(cls, **kwargs):
        """An action that forgets who may take it, or says it can be undone without saying how, fails
        when its module is imported rather than at the first refusal."""
        super().__init_subclass__(**kwargs)
        if "verb" in cls.__dict__ and not hasattr(cls, "who"):
            raise TypeError(f"{cls.__name__} does not declare who may take it")
        if cls.reversible and cls.undo is Action.undo:
            raise TypeError(f"{cls.__name__} is reversible but has no undo()")

    def __init__(self, obj: Any = None):
        self.object = obj

    @property
    def context(self) -> Context:
        return Context.current()

    @property
    def subject(self) -> Caller:
        return self.context.subject

    def check(self) -> None:
        """Refuse an action that is malformed or not possible now; nothing by default."""

    def authorize(self) -> None:
        """Refuse, saying why, unless its rule lets the subject take it."""
        self.who.require(self)

    def describe(self) -> list[str]:
        """What it will do, line by line."""
        return [f"{self.verb} {getattr(self.object, 'id', self.object) or ''}".rstrip()]

    def run(self) -> Any:
        raise NotImplementedError

    def undo(self) -> None:
        raise NotImplementedError(f"{self.verb} cannot be undone")

    # --- performing it: what every action that changes something shares ---------------------

    needs: ClassVar[list[str]] = FS_CHECKS  # the doctor checks it depends on

    def perform(self, go_ahead: Callable[[list[str]], bool] = lambda plan: True) -> Any:
        """Check, authorize and describe it; ask `go_ahead` with the plan (False for a dry run or a no);
        then, inside the lock, check and authorize again from a fresh read of the disk, refuse if the plan
        changed while the user was deciding, and run it. Returns what `run` returns, or None if it did not run.
        An action that changes nothing is only checked, authorized and run, and returns what it read."""
        if not self.changes:
            self.check()
            self.authorize()
            return self.run()
        c = self.context
        c.act(self.needs)
        self.check()
        self.authorize()
        plan = self.describe()
        if not go_ahead(plan):
            return None
        with locked() if self.locks else contextlib.nullcontext():
            c.refresh()
            self.check()
            self.authorize()
            if self.describe() != plan:
                raise Refused("something changed while you were deciding; run it again to see the new plan")
            try:
                return self.run()
            finally:
                c.refresh()  # what it changed is what the next reader sees


class SessionAction(Action):
    """An action on one session, which its rule usually allows by the subject's relation to it."""

    @property
    def session(self):
        return self.object

    @property
    def label(self) -> str:
        return self.context.name_of(self.object.id) or self.object.id


class Transaction(Action):
    """Actions done all or nothing: each is checked and authorized before any runs; they run in order
    under one lock; if one fails, those already run are undone, newest first. Every action but the last
    must be reversible, so nothing after an irreversible one can fail."""

    verb = "transaction"
    who = Anyone("each step is authorized as its own verb")

    def __init__(self, actions: list[Action]):
        super().__init__(actions)
        if bad := [a.verb for a in actions[:-1] if not a.reversible]:
            raise Refused(f"{', '.join(bad)} cannot be undone, so it may only be a transaction's last step")
        self.actions = actions
        self.needs = sorted({n for a in actions for n in a.needs})

    def check(self) -> None:
        for a in self.actions:
            a.check()

    def authorize(self) -> None:
        for a in self.actions:
            a.authorize()

    def describe(self) -> list[str]:
        return [line for a in self.actions for line in a.describe()]

    def run(self) -> list[Any]:
        done, results = [], []
        try:
            for a in self.actions:
                results.append(a.run())
                done.append(a)
        except Exception as failure:
            # Every undo is tried, newest first, even if one fails; the original failure is what is
            # raised, with what could not be put back said alongside it.
            stuck = []
            for a in reversed(done):
                try:
                    a.undo()
                except Exception as e:
                    stuck.append(f"{a.verb}: {e}")
            if stuck:
                raise Refused(f"{failure}; and these could not be undone: {'; '.join(stuck)}") from failure
            raise
        return results


class Workflow:
    """Steps in order, with waits between them; not all or nothing: it stops at the first failure,
    then runs its `always` steps (such as stopping what it started), and says how far it got. Every
    step's permission is checked before the first runs; each step is checked
    just before it runs, since an earlier step changes what a later one finds. It runs inside whatever
    lock its caller holds, so its steps are run, not performed."""

    def __init__(self, steps: list[Action], always: list[Action] | None = None):
        self.steps, self.always = steps, always or []

    def authorize(self) -> None:
        for step in self.steps + self.always:
            step.authorize()

    def describe(self) -> list[str]:
        return [line for step in self.steps for line in step.describe()]

    def run(self) -> list[Any]:
        results: list[Any] = []
        done = 0
        failure: BaseException | None = None
        try:
            for step in self.steps:
                step.check()
                results.append(step.run())
                done += 1
        except BaseException as e:  # noqa: BLE001 - re-raised below, after the closing steps
            failure = e
        closing: list[str] = []
        for step in self.always:  # every closing step is tried, and none hides the failure that came first
            try:
                step.check()
                results.append(step.run())
            except Exception as e:  # noqa: BLE001
                closing.append(f"{step.verb}: {e}")
        if failure is not None:
            if isinstance(failure, Refused):
                note = f"; then {'; '.join(closing)}" if closing else ""
                raise Refused(f"{failure} (after {done} of {len(self.steps)} steps{note})") from failure
            raise failure
        if closing:
            raise Refused(f"the work was done, but closing it failed: {'; '.join(closing)}")
        return results


def tmux(socket: str | None = None):
    """claudestra's tmux server; a socket other than the default is for tests. libtmux is imported
    only by the actions that use it."""
    from ..runners.tmux import Tmux

    return Tmux(socket)


class ReadOnlyAction(Action):
    """An action that changes nothing: anyone may take it, with no lock and no confirmation; `perform`
    returns what it read for the caller to print."""

    who = Anyone()
    changes = False
