"""`claudestra staff dismiss`: take a staffer off the staff. Its staff file moves to staff-dismissed.d/ as it
is, and `claudestra staff hire` brings it back; its session is untouched, and so is any scope it holds in
trust.yaml, which it holds again once rehired. Refused while it runs in claudestra's tmux or a machine
starts it at login, since either would leave something nobody answers for.
"""

from __future__ import annotations

from ..caller import Refused
from ..ops import staff as staff_ops
from ..ops.common import log
from .base import SessionAction
from .permissions import D_UNMANAGED, MANAGER, USER, Relations


class Dismiss(SessionAction):
    """On a staffer (claudestra.session.Staffer)."""

    verb = "dismiss"
    who = Relations(frozenset({USER, MANAGER, D_UNMANAGED}))
    needs: list[str] = []
    reversible = True

    def __init__(self, staffer, socket: str | None = None):
        super().__init__(staffer)
        self.socket = socket

    @property
    def staffer(self):
        return self.object

    def check(self) -> None:
        c, st = self.context, self.staffer
        st.staff_file  # noqa: B018 - refuses one no longer on the staff
        if hosts := [m.hostname for m in c.trust.machines.values() if st.id in m.autostart]:
            raise Refused(f"{st.staff_name!r} starts at login on {', '.join(hosts)}; take it out of autostart first")
        if (w := st.window(self.socket)) and not w.dead:
            raise Refused(f"{st.staff_name!r} is running in claudestra's tmux; stop it first")

    def describe(self) -> list[str]:
        st = self.staffer
        scope = f"; its {st.scope} scope stays in trust.yaml for a rehire" if st.scope else ""
        older = (
            " (over an older dismissed copy)"
            if staff_ops.dismissed_path(self.context.trust.config, st.id).exists()
            else ""
        )
        return [f"dismiss {st.staff_name!r} ({st.id}): {st.staff_file.file.name} to staff-dismissed.d/{older}{scope}"]

    def run(self) -> None:
        st = self.staffer
        name = st.staff_name
        self.older = staff_ops.dismiss(self.context.trust.config, st.id)
        log(self.subject, "dismiss", st.id, f"{name!r}")

    def undo(self) -> None:
        staff_ops.undismiss(self.context.trust.config, self.staffer.id, getattr(self, "older", None))
        self.context.refresh()
