"""`claudestra session compact`: compact a stopped session.

Compaction needs the model, so a Claude Code process. The session is resumed in claudestra's tmux from
the folder it is filed under, exactly as `claudestra session start` would; `/compact` is typed into it once it is
idle; and it is stopped again once its transcript records the compaction. It is authorized as one verb,
and runs as a workflow of Start, waits, Type and Stop. A running session is refused: /compact is typed
in it by hand.
"""

from __future__ import annotations

from ..caller import Refused
from ..ops import compact as compact_ops
from ..ops.common import log
from .base import SessionAction, Workflow
from .permissions import D_MANAGER, D_UNMANAGED, MANAGER, USER, Relations
from .start import Start, launch
from .stop import Stop
from .type import Type
from .wait import Wait

READY_WAIT = 120.0  # seconds for the resumed session to come up idle


class Compact(SessionAction):
    verb = "compact"
    who = Relations(frozenset({USER, MANAGER, D_MANAGER, D_UNMANAGED}))
    needs = ["pid-files", "proc-start", "slug-rule"]

    def __init__(self, session, claude: str, instructions: str = "", timeout: float = 600.0, socket: str | None = None):
        super().__init__(session)
        self.claude, self.instructions, self.timeout, self.socket = claude, instructions, timeout, socket

    def check(self) -> None:
        r = self.session.record
        if r is None:
            raise Refused(f"{self.session.id} has no transcript on this machine")
        if pid := self.session.running_pid:
            raise Refused(f"{self.session.id} is running (pid {pid}); type /compact in it")
        launch(self.session)  # refuses one whose folder is not known

    def describe(self) -> list[str]:
        s = self.session
        what = f"/compact {self.instructions}".strip()
        return [f"compact {s.id} ({s.name or '-'}): resume it in claudestra's tmux, type {what}, then stop it"]

    def workflow(self) -> Workflow:
        c, s = self.context, self.session
        transcript = s.transcript
        before = transcript.stat().st_size

        def compacted() -> bool:
            with transcript.open("rb") as fh:
                fh.seek(before)
                return compact_ops.BOUNDARY in fh.read()

        def idle() -> bool:
            return compact_ops.status(c.fs, s.id) == "idle"

        return Workflow(
            [
                Start(s, self.claude, self.socket),
                Wait("the session to come up idle", idle, READY_WAIT),
                Type(s, f"/compact {self.instructions}".strip(), self.socket),
                Wait("the compaction to be recorded", compacted, self.timeout),
                Wait("the session to settle after compacting", idle, self.timeout),
            ],
            always=[Stop(s, force=True, socket=self.socket)],
        )

    def authorize(self) -> None:
        """Compact itself, and every step of its workflow, before the first runs."""
        super().authorize()
        self.workflow().authorize()

    def run(self) -> list[str]:
        results = self.workflow().run()
        out = [r for r in results if isinstance(r, str)]
        out.insert(1, f"compacted {self.session.id}")
        log(self.subject, "compact", self.session.id, "; ".join(out))
        return out
