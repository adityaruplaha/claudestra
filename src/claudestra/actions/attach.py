"""`claudestra session attach`: join claudestra's tmux session, at one session's window if one is named. The
user's alone; it replaces this process with tmux."""

from __future__ import annotations

import os

from ..caller import Refused
from ..runners import TMUX_SESSION
from .base import Action, tmux
from .permissions import Kinds


class Attach(Action):
    verb = "attach"
    who = Kinds(frozenset({"human"}))
    needs: list[str] = []
    locks = False  # this process becomes tmux, which would hold the lock for as long as the user is attached

    def __init__(self, socket: str | None = None, session_id: str | None = None, name: str | None = None):
        super().__init__(session_id)
        self.socket, self.name = socket, name or session_id
        self.window: str | None = None

    def check(self) -> None:
        if self.object is None:
            return
        w = tmux(self.socket).window(self.object)
        if w is None:
            raise Refused(f"{self.name!r} has no window in claudestra's tmux; start it with `claudestra session start`")
        self.window = w.id

    def describe(self) -> list[str]:
        at = f", at {self.name}'s window" if self.object else ""
        return [f"attach to tmux session {TMUX_SESSION}{at}"]

    def run(self) -> None:
        sock = ["-L", self.socket] if self.socket else []
        env = dict(os.environ)
        here = os.environ.get("TMUX", "").split(",")[0]
        same_server = bool(here) and os.path.basename(here) == (self.socket or "default")
        if here and not same_server:
            env.pop("TMUX", None)  # inside another tmux server: nest, which tmux allows once told
        target = f"={TMUX_SESSION}"
        argv = ["tmux", *sock]
        if not self.window:
            argv += ["switch-client" if same_server else "attach-session", "-t", target]
        else:
            # A session of its own, grouped with claudestra's, so that going to this window moves no one else who
            # is attached. It is destroyed once unattached, which tmux would do at once to one not yet attached,
            # so that is set after the client is on it.
            view = f"{TMUX_SESSION}-view-{os.getpid()}"
            if same_server:
                argv += [
                    "new-session",
                    "-d",
                    "-t",
                    target,
                    "-s",
                    view,
                    ";",
                    "select-window",
                    "-t",
                    f"{view}:{self.window}",
                ]
                argv += [";", "switch-client", "-t", view, ";", "set-option", "-t", view, "destroy-unattached", "on"]
            else:
                argv += ["new-session", "-t", target, "-s", view, ";", "set-option", "destroy-unattached", "on"]
                argv += [";", "select-window", "-t", f"{view}:{self.window}"]
        os.execvpe("tmux", argv, env)
