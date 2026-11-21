"""`claudestra staff rotate`: give a staffer a new session, keeping its place on the staff.

Its main use is a staffer whose conversation is gone (`audit`'s staff report), which cannot be resumed. The
new session is begun in the staffer's folder on this machine and takes over its staff file, name,
description and every machine's folder, and in trust.yaml its scope and its place in any machine's autostart.
Who answers to it is worked out from folders, so a rotated manager's staffers answer to the new session with
nothing rewritten. A staffer whose old session still has a transcript here is rotated only while that
session is stopped, and the old session goes to the trash, where `claudestra trash restore` finds it.

The new session's first prompt is an opening written from the staff file, then the brief given; a session
that rotates a staffer must give the brief, since only it knows where the work stands. Who may rotate is
who may dismiss: the user, the staffer's manager, or the device scope where no manager holds it. A staffer
with a scope or one that starts at login is the user's alone, since rotating it rewrites trust.yaml.
"""

from __future__ import annotations

import uuid

from .. import portable
from ..caller import Refused
from ..ops import open_items as items_ops
from ..ops import staff as staff_ops
from ..ops import trash as trash_ops
from ..ops import trust_file
from ..ops.common import log
from ..runners import Launch
from ..trust import tilde
from .base import SessionAction, tmux
from .permissions import D_UNMANAGED, MANAGER, USER, Relations, require_kind


class Rotate(SessionAction):
    """On a staffer (claudestra.session.Staffer)."""

    verb = "rotate"
    who = Relations(frozenset({USER, MANAGER, D_UNMANAGED}))
    needs = ["pid-files", "proc-start", "remote-control"]
    reversible = True

    def __init__(
        self,
        staffer,
        claude: str,
        prompt: str | None = None,
        recent_minutes: float = 10.0,
        socket: str | None = None,
        reason: str | None = None,
    ):
        super().__init__(staffer)
        self.new = str(uuid.uuid4())
        self.claude, self.socket, self.recent_minutes = claude, socket, recent_minutes
        self.reason = (reason or "").strip() or None
        self.brief = (prompt or "").strip() or None
        self.plan: trash_ops.Plan | None = None
        self.entry = None  # the old session's trash entry, once trashed
        self.rehomed: str | None = None  # the staff file's text before, once moved
        self.items_moved = False
        self.trust_before: str | None | bool = False  # False: trust.yaml not changed

    @property
    def staffer(self):
        return self.object

    def _in_trust(self) -> bool:
        """Whether trust.yaml names the old session: a scope, or a place in any machine's autostart."""
        t, sid = self.context.trust, self.staffer.id
        return sid in t.scopes or any(sid in m.autostart for m in t.machines.values())

    def check(self) -> None:
        c, st = self.context, self.staffer
        sf = st.staff_file  # refuses one no longer on the staff
        host = c.machine.hostname
        if sf.folder is None:
            raise Refused(f"{sf.name!r} has no folder on {host}; rotate it on the machine it lives on")
        if not sf.folder.is_dir():
            raise Refused(f"{sf.name!r} works in {sf.folder}, which is not a folder")
        if (w := st.window(self.socket)) and not w.dead:
            raise Refused(f"{sf.name!r} is running in claudestra's tmux; stop it first")
        if pid := st.running_pid:
            raise Refused(f"{sf.name!r} is running (pid {pid}); stop it first")
        r = st.record
        if r is None and (others := [str(h) for h in sf.folders if str(h).lower() != host.lower()]):
            raise Refused(f"{sf.name!r} has no transcript here and may live on {', '.join(others)}; rotate it there")
        self.plan = trash_ops.plan(c.fs, c.trust, r, self.recent_minutes) if r is not None else None
        if self.reason is None:
            raise Refused("say why it is rotated, for its history, with --reason")
        if self.brief is None and self.subject.kind != "human":
            raise Refused("a session that rotates a staffer gives its brief, where the work stands; use --prompt")

    def authorize(self) -> None:
        super().authorize()
        if self._in_trust():
            require_kind(
                f"rotating {self.staffer.staff_name!r}, whose scope or autostart is in trust.yaml,",
                self.subject,
                frozenset({"human"}),
            )

    @property
    def prompt(self) -> str:
        """The opening, written from the staff file, then the brief."""
        c, st = self.context, self.staffer
        sf = st.staff_file
        old = "is in claudestra's trash" if self.plan else "Claude Code deleted, so it cannot be resumed"
        scope = (
            f" You hold its {st.scope} scope; `claudestra staff list --tree` shows who answers to you."
            if st.scope
            else ""
        )
        opening = (
            f"You are {sf.name}, a staffer claudestra has rotated: you replace session {st.id}, whose conversation "
            f"{old}. Your staff file says you work on: {sf.description}. You work in {tilde(sf.folder, c.fs.home)} "
            f"and answer to {st.managed_by}.{scope} Load the claudestra:cli and claudestra:coordination skills; "
            "`claudestra whoami` says what you may do."
        )
        return opening + (f"\n\n{self.brief}" if self.brief else "")

    @property
    def launch(self) -> Launch:
        sf = self.staffer.staff_file
        return Launch(self.new, sf.name, sf.folder, new=True, prompt=self.prompt)

    def describe(self) -> list[str]:
        from ..runners import tmux as runner

        c, st = self.context, self.staffer
        sf = st.staff_file
        out = []
        if p := self.plan:
            out.append(f"trash {st.id} ({p.session.name or '-'}): {len(p.items)} stores, {p.bytes / 1e6:.2f} MB")
        else:
            out.append(f"{st.id} has no transcript here: its conversation is gone")
        out.append(f"staff file of {sf.name!r}: {st.id}.yaml to {self.new}.yaml")
        if self._in_trust():
            out.append(f"trust.yaml: {st.id}'s scope and autostart to {self.new}")
        out.append(runner.start(c.fs, c.machine.hostname, tmux(self.socket), self.launch, self.claude, dry=True))
        return out

    def run(self) -> str:
        from ..runners import tmux as runner

        c, st = self.context, self.staffer
        old, name = st.id, st.staff_name
        in_trust = self._in_trust()
        try:
            launch = self.launch  # its prompt is read from the staff file while it is still the old one's
            if self.plan:
                self.entry = trash_ops.apply(c.fs, self.subject, self.plan, reason=f"rotated to {self.new}")
            self.rehomed = staff_ops.rehome(c.trust.config, old, self.new, portable.now_local(), self.reason)
            items_ops.follow(c.trust.config, old, self.new)
            self.items_moved = True
            c.refresh()
            if in_trust:
                self.trust_before = trust_file.change(c.trust.trust_file, self._renamer(old, self.new), c.name_of)
            log(self.subject, "rotate", self.new, f"{name!r}, replacing {old}")
            line = runner.start(c.fs, c.machine.hostname, tmux(self.socket), launch, self.claude, dry=False)
        except Exception:
            self.undo()
            raise
        if line.startswith("exited"):  # it never ran, so the staffer is put back as it was
            self.undo()
            return f"{line}; the rotate is undone"
        log(self.subject, "spawn", self.new, line)
        return f"{line}\nsession {self.new}"

    @staticmethod
    def _renamer(old: str, new: str):
        def edit(raw: dict) -> None:
            raw["sessions"] = {(new if k == old else k): v for k, v in raw["sessions"].items()}
            for m in raw["machines"].values():
                if m.get("autostart"):
                    m["autostart"] = [new if s == old else s for s in m["autostart"]]

        return edit

    def undo(self) -> None:
        """Put the staffer back on its old session: the new one stopped and trashed, trust.yaml and the staff
        file as they were, and the old session back from the trash."""
        from ..runners import tmux as runner

        c, old = self.context, self.staffer.id
        failed = []
        try:
            runner.stop(c.fs, tmux(self.socket), self.new, self.new[:8], dry=False, force=True)
            c.refresh()
            if (r := c.model.sessions.get(self.new)) is not None:
                trash_ops.apply(c.fs, self.subject, trash_ops.plan(c.fs, c.trust, r, 0), reason="a rotate undone")
        except Exception as e:  # noqa: BLE001 - the rest is put back regardless
            failed.append(f"the new session {self.new}: {e}")
        if self.trust_before is not False:
            trust_file.restore(c.trust.trust_file, self.trust_before)
            self.trust_before = False
        if self.items_moved:
            items_ops.follow(c.trust.config, self.new, old)
            self.items_moved = False
        if self.rehomed is not None:
            staff_ops.unrehome(c.trust.config, old, self.new, self.rehomed)
            self.rehomed = None
        if self.entry is not None:
            trash_ops.restore(c.fs, self.subject, self.entry.name, dry=False)
            self.entry = None
        c.refresh()
        if failed:
            raise Refused(f"the staffer is back on {old}, but {'; '.join(failed)}")
