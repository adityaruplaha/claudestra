"""The context: one per process, holding what every action reads (DESIGN.md §4).

Claude Code's files, this machine, the trust config, and the subject: who is calling, as the process
chain shows it. Everything else reaches it through `Context.current()`, so nothing passes these
around. The model is read from disk when asked and read again with `refresh()`, since Claude Code
changes those files underneath any copy.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import ClassVar

from . import checks
from .caller import Caller, Refused, identify
from .claude_fs import ClaudeFS
from .model import Machine, Model, build
from .proctree import ClaudeProc, claude_chain
from .trust import CONFIG_ENV, Trust, load, machine_problem, tilde


class Context:
    _current: ClassVar[Context | None] = None

    def __init__(
        self,
        home: Path | None = None,
        config: Path | None = None,
        *,
        proc: Path | None = None,
        start_pid: int | None = None,
    ):
        """`home` and `config` are the user's to override; `proc` and `start_pid` are for tests, which point
        claudestra at a fixture /proc and the process its chain starts from."""
        if Context._current is not None:
            raise RuntimeError("a claudestra context already exists in this process; there is one per process")
        # Pointing claudestra at another home or config could hand a caller a scope it lacks, so
        # either is honoured for the user only (act).
        self.overridden = home is not None or config is not None or CONFIG_ENV in os.environ
        self.fs = ClaudeFS(home, proc=proc) if proc else ClaudeFS(home)
        self._start_pid = start_pid
        self.machine = Machine.here(self.fs.home)
        self._config = config
        self.trust: Trust = load(self.machine.hostname, self.fs.home, config)
        self._model: Model | None = None
        self._subject: Caller | None = None
        self._chain: list[ClaudeProc] | None = None
        Context._current = self

    @classmethod
    def current(cls) -> Context:
        if cls._current is None:
            raise RuntimeError("no claudestra context; the command line creates it")
        return cls._current

    @classmethod
    def reset(cls) -> None:
        """Forget the current context, so another can be created (tests; one command per process otherwise)."""
        cls._current = None

    @classmethod
    @contextmanager
    def use(cls, home: Path | None = None, config: Path | None = None, **test_hooks) -> Iterator[Context]:
        """A context of its own for the duration, the previous one put back after (tests)."""
        previous, cls._current = cls._current, None
        try:
            yield cls(home, config, **test_hooks)
        finally:
            cls._current = previous

    @classmethod
    def for_test(
        cls, home: Path, config: Path, subject: Caller, chain: list[ClaudeProc] | None = None, **hooks
    ) -> Context:
        """A context for a test that acts as `subject`, with `chain` as the Claude processes found (none
        unless given). A fixture home and config are then not an override: they are the test's world."""
        c = cls(home, config, **hooks)
        c.overridden, c._subject, c._chain = False, subject, list(chain or [])
        return c

    # --- what it reads ------------------------------------------------------------------------

    @property
    def model(self) -> Model:
        if self._model is None:
            self._model = build(self.fs, self.trust, self.machine)
        return self._model

    def refresh(self) -> Model:
        """The config and the model read again: inside the lock before an action runs, and after it,
        since an action may have changed either (a rename changes a staff file's name)."""
        self.trust = load(self.machine.hostname, self.fs.home, self._config)
        self._model = None
        return self.model

    @property
    def subject(self) -> Caller:
        """Who is calling, from the process chain, never from an argument (DESIGN.md §6.4)."""
        if self._subject is None:
            self._subject = identify(self.fs, self.machine.hostname, self.trust, start_pid=self._start_pid)
        return self._subject

    @property
    def chain(self) -> list[ClaudeProc]:
        """The Claude processes in the chain that called claudestra, nearest first, each with its session
        where a live session file names it. The nearest is the subject; the rest are those it runs under."""
        if self._chain is None:
            self._chain = claude_chain(self.fs, self._start_pid)
        return self._chain

    def chain_sessions(self) -> list[str | None]:
        """The session ID of each Claude process in the chain, nearest first; None where none matches.
        Normally one; two or more when a Claude session runs claudestra inside another's terminal."""
        return [c.session_id for c in self.chain]

    RESTRICTED = (
        "restricted mode: a Claude process is in the chain that called claudestra, so a Claude session may be running it;"
        " what is the user's alone is refused"
    )

    @property
    def restricted(self) -> bool:
        """Whether claudestra runs under Claude: any Claude process in the chain, however far up.

        Then whatever is the user's alone is refused, whoever the subject is taken to be, since a Claude session may
        be driving the terminal. It is decided from the chain, never from the environment."""
        return bool(self.chain)

    def caller_line(self) -> str:
        """Who the nearest Claude process in the chain is, in one line: its session, its name on the staff,
        and its scope and where it applies. Read from the chain and the config alone, so it can
        be said even where identifying the subject would refuse."""
        if not self.chain:
            return "caller: no Claude process in the chain"
        near = self.chain[0]
        if near.session_id is None:
            return f"caller: a Claude process (pid {near.proc.pid}) with no session file, so no session can be named"
        sid, home = near.session_id, self.fs.home
        sf = self.trust.staff_file(sid)
        who = f"session {sid}" + (f" ({sf.name})" if sf else f" ({near.session_name})" if near.session_name else "")
        if sf is None:
            return f"caller: {who}, not on the staff, so no scope"
        scope = self.trust.scope(sid)
        if sf.folder is not None:
            where = f"over {tilde(sf.folder, home)}" if scope == "folder" else "on this machine"
        else:
            where = "on " + ", ".join(sorted(sf.folders)) if sf.folders else "with no folder on any machine"
        return f"caller: {who}, " + (f"{scope} scope {where}" if scope else f"a specialist (no scope), {where}")

    def act(self, needs: list[str], machine_known: bool = True) -> Caller:
        """The preamble of every action that changes something; returns the subject, or refuses. An action that
        describes this machine in trust.yaml does not need it described already (`machine_known`)."""
        if machine_known and (
            why := machine_problem(self.machine.hostname, self.machine.machine_id, self.trust.machines)
        ):
            raise Refused(f"this machine does not match trust.yaml: {why}")
        if self.trust.errors:
            raise Refused("the config has errors; see claudestra check")
        subject = self.subject
        if self.overridden and subject.kind != "human":
            raise Refused(f"--home, --config and ${CONFIG_ENV} are honoured for the user only")
        if failed := checks.require(self.fs, needs):
            raise Refused("claudestra doctor fails " + "; ".join(f"{r.name} ({r.detail})" for r in failed))
        return subject

    # --- sessions -----------------------------------------------------------------------------

    def resolve(self, token: str) -> list:
        """Sessions matching a full ID, an 8+ character prefix, a bridge ID, a job's short ID, or a name."""
        from .session import Session

        return [Session(r.session_id) for r in self.model.resolve(token)]

    def session(self, ref: str):
        """Any session, by a full ID, an 8+ character prefix, a bridge ID, a job's short ID, its title,
        or a staffer's name. Always a plain Session, for callers that do not care whether it is on the
        staff; one that does asks `on_staff`, and one that needs a staffer calls `staffer` instead."""
        from .session import Session

        if (sf := self.trust.named(ref)) is not None or (sf := self.trust.staff_file(ref.strip().lower())) is not None:
            return Session(sf.session)  # a staffer whose session may be on another machine
        hits = self.resolve(ref)
        if not hits:
            raise Refused(f"no session matches {ref!r}")
        if len(hits) > 1:
            raise Refused(f"{ref!r} matches {len(hits)} sessions: " + ", ".join(f"{s.id} ({s.name})" for s in hits))
        return hits[0]

    def staffer(self, ref: str):
        """A staffer, by its name, its session's full ID or an 8+ character prefix of it, or anything
        `session` takes; refused if no staff file names it."""
        from .session import Staffer

        t = ref.strip()
        sf = self.trust.named(t) or next(
            (f for f in self.trust.staff if len(t) >= 8 and f.session.startswith(t.lower())), None
        )
        if sf is None:
            s = self.session(t)
            if (sf := self.trust.staff_file(s.id)) is None:
                raise Refused(f"{ref!r} is not on the staff")
        return Staffer(sf.session)

    def staff(self) -> list:
        """Every staffer, as the staff files list them."""
        from .session import Staffer

        return [Staffer(sf.session) for sf in self.trust.staff]

    def sessions(self) -> list:
        from .session import Session

        return [Session(sid) for sid in self.model.sessions]

    def name_of(self, session_id: str) -> str | None:
        """A session's name: its staff file's, or its title on this machine."""
        if (a := self.trust.staff_file(session_id)) is not None:
            return a.name
        r = self.model.sessions.get(session_id)
        return r.name if r else None

    # --- the actions whose object is not one session ----------------------------------------

    def restore(self, entry: str):
        from .actions.restore import Restore

        return Restore(entry)

    def purge(self, older_than_days: float):
        from .actions.purge import Purge

        return Purge(older_than_days)

    def fetch(
        self, session_id: str, host: str, src: str | None = None, dest: Path | None = None, copy_memory: bool = False
    ):
        from .actions.fetch import Fetch

        return Fetch(session_id, host, src, dest, copy_memory)

    def attach(self, socket: str | None = None, session_id: str | None = None, name: str | None = None):
        from .actions.attach import Attach

        return Attach(socket, session_id, name)

    def install_login_unit(self):
        from .actions.install_unit import InstallUnit

        return InstallUnit()

    def install_guard(self):
        from .actions.install_guard import InstallGuard

        return InstallGuard()

    def spawn(self, folder, claude: str, prompt=None, name=None, staff: bool = False, description=None, socket=None):
        from .actions.spawn import Spawn

        return Spawn(folder, claude, prompt, name, staff, description, socket)

    def install_completion(self, shell=None):
        from .actions.install_completion import InstallCompletion

        return InstallCompletion(shell)

    def enable_remote_control(self):
        from .actions.enable_remote_control import EnableRemoteControl

        return EnableRemoteControl()
