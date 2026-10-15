"""`claudestra trust autostart add|remove`: which staffers a machine's login unit starts. The user's alone."""

from __future__ import annotations

from ..caller import Refused
from ..ops import trust_file
from .base import Action
from .permissions import Kinds


class TrustAutostart(Action):
    verb = "trust autostart"
    who = Kinds(frozenset({"human"}))
    needs: list[str] = []
    reversible = True

    def __init__(self, session_id: str, add: bool, host: str | None = None):
        super().__init__(session_id)
        self.add, self.host = add, host
        self.before: str | None = None

    def _host(self) -> str:
        return self.host or self.context.machine.hostname

    def check(self) -> None:
        c, sid, host = self.context, self.object, self._host()
        mc = c.trust.machines.get(host.lower())
        if mc is None:
            raise Refused(f"{host} is not under machines in trust.yaml; add it with `claudestra trust machine add`")
        if self.add:
            sf = c.trust.staff_file(sid)
            if sf is None or not any(h.lower() == host.lower() for h in sf.folders):
                raise Refused(f"{sid} is not a staffer with a folder on {host}, so its login unit could not start it")
            if sid in mc.autostart:
                raise Refused(f"{sid} already starts at login on {host}")
        elif sid not in mc.autostart:
            raise Refused(f"{sid} does not start at login on {host}")

    def describe(self) -> list[str]:
        sid = self.object
        how = "starts" if self.add else "no longer starts"
        return [f"trust.yaml: {sid} ({self.context.name_of(sid) or '-'}) {how} at login on {self._host()}"]

    def run(self) -> None:
        c, sid, host = self.context, self.object, self._host()

        def edit(raw: dict) -> None:
            mc = next(v for k, v in raw["machines"].items() if str(k).lower() == host.lower())
            listed = mc.setdefault("autostart", [])
            if self.add:
                listed.append(sid)
            else:
                listed.remove(sid)

        self.before = trust_file.change(c.trust.trust_file, edit, c.name_of)

    def undo(self) -> None:
        trust_file.restore(self.context.trust.trust_file, self.before)
        self.context.refresh()
