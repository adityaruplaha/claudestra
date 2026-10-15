"""Runners start and stop sessions (DESIGN.md §7). The names here are the ones other modules need
without importing a runner and its dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

TMUX_SESSION = "claudestra"  # the tmux session claudestra keeps its sessions in, one window each
UNIT = "claudestra-autostart.service"  # the login unit that runs `claudestra start --autostart`


@dataclass(frozen=True)
class Launch:
    """What a runner needs to run a session, and nothing about who it is: its ID, the name it is shown
    and reached by, and the folder it resumes in without forking."""

    session: str
    name: str
    folder: Path
