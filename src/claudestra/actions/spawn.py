"""`claudestra session spawn`: begin a new session in a folder, in claudestra's tmux, with Remote Control on.

The session's ID is chosen here, so it can be named and reached from the moment it starts. It takes a
first prompt and a name, and with `--staff` is hired into the folder as a specialist; scope stays the
user's to grant (`trust`). A session spawned by a session is always hired, with its brief, so that its
spawner can run it and it writes a transcript at once; only the user spawns a session off the staff. It
starts in the user's default permission mode, whatever the spawner's. If it exits at once, its hire is
taken back.

Who may spawn is worked out from the folder, as the relation the subject would have to the new session:
the user, anywhere; a device scope, anywhere on its machine, protected folders included; a manager, inside
its own folder. Where a manager holds the folder, the device scope does not spawn there itself: it asks that
manager, by message, to spawn the specialist, so the work starts under the manager that will run it.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from ..caller import Refused
from ..ops import staff as staff_ops
from ..ops.common import log
from ..ops.rename import check_name
from ..runners import Launch
from ..session import Session
from ..trust import tilde
from .base import SessionAction, tmux
from .permissions import D_MANAGED, D_UNMANAGED, MANAGER, USER, ToFolder, relation_to_folder


class Spawn(SessionAction):
    verb = "spawn"
    who = ToFolder(frozenset({USER, MANAGER, D_UNMANAGED}))
    needs = ["pid-files", "proc-start", "remote-control"]

    def __init__(
        self,
        folder: Path,
        claude: str,
        prompt: str | None = None,
        name: str | None = None,
        staff: bool = False,
        description: str | None = None,
        socket: str | None = None,
    ):
        super().__init__(Session(str(uuid.uuid4())))
        self.folder = Path(folder).expanduser().absolute()
        self.claude, self.socket = claude, socket
        self.prompt = (prompt or "").strip() or None
        self.name = check_name(name) if name else None
        self.staff, self.description = staff, (description or "").strip()

    @property
    def folder_here(self) -> Path:
        return self.folder

    def check(self) -> None:
        c = self.context
        if self.subject.kind != "human":
            self.staff = True  # a session's spawn is always hired, so that its spawner can run it
        if not self.folder.is_dir():
            raise Refused(f"{self.folder} is not a folder")
        if not self.staff:
            if self.description:
                raise Refused("--description is for a staffer; add --staff")
            return
        if not self.name:
            raise Refused("a staffer needs a name, and a session's spawn is always a staffer; give one with --name")
        if not self.description:
            raise Refused("a staffer's description says what it works on; give one with --description")
        if not self.prompt:
            raise Refused("a staffer is spawned with its brief; give it with --prompt")
        if clash := next((f for f in c.trust.staff if f.name == self.name), None):
            raise Refused(f"the staffer {clash.session} is already named {self.name!r}; give another with --name")

    def authorize(self) -> None:
        if relation_to_folder(self.subject, self.folder, self.session.id) == D_MANAGED:
            managers = ", ".join(repr(m.name) for m in self.context.trust.managers_of(self.folder))
            raise Refused(
                f"{managers} manages {self.folder}; ask it by message to spawn the specialist there, "
                "so the work starts under the manager that will run it"
            )
        super().authorize()

    @property
    def launch(self) -> Launch:
        return Launch(self.session.id, self.name or self.session.id[:8], self.folder, new=True, prompt=self.prompt)

    def describe(self) -> list[str]:
        from ..runners import tmux as runner

        c = self.context
        out = [runner.start(c.fs, c.machine.hostname, tmux(self.socket), self.launch, self.claude, dry=True)]
        if self.staff:
            out.append(
                f"hire {self.session.id} as {self.name!r}, working in {tilde(self.folder, c.fs.home)}: {self.description}"
            )
        return out

    def run(self) -> str:
        from ..runners import tmux as runner

        c = self.context
        if self.staff:  # first, so that the session is a staffer from its first turn
            folders = {c.machine.hostname: tilde(self.folder, c.fs.home)}
            staff_ops.hire(c.trust.config, self.session.id, self.name, folders, self.description)
            log(self.subject, "hire", self.session.id, f"as {self.name!r}, spawned")
        try:
            line = runner.start(c.fs, c.machine.hostname, tmux(self.socket), self.launch, self.claude, dry=False)
        except Exception:
            if self.staff:
                staff_ops.unhire(c.trust.config, self.session.id, None)
            raise
        if self.staff and line.startswith("exited"):  # it never ran, so it is no staffer
            staff_ops.unhire(c.trust.config, self.session.id, None)
            line += "; its hire is taken back"
        log(self.subject, "spawn", self.session.id, line)
        return f"{line}\nsession {self.session.id}"
