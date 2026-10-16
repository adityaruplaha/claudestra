"""What every test shares: fixture homes (a fake ~/.claude and config/ in a temporary folder), a fake
/proc, claudestra's state redirected into the temporary folder, and the stand-ins for the user and the other
machine. Tests never read real sessions."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from claudestra import context as context_mod
from claudestra import portable
from claudestra.caller import Caller
from claudestra.claude_fs import ClaudeFS
from claudestra.cli import ui
from claudestra.context import Context
from claudestra.model import Machine, Model, build
from claudestra.ops import common, transfer
from claudestra.portable import slug
from claudestra.trust import MachineConf, Trust, load

A = "aaaaaaaa-1111-4111-8111-111111111111"
B = "bbbbbbbb-2222-4222-8222-222222222222"
C = "cccccccc-3333-4333-8333-333333333333"
D = "dddddddd-4444-4444-8444-444444444444"
HOST = "testhost"
HERE = socket.gethostname()  # what a context reads as this machine
HUMAN = Caller("human")


class Home:
    def __init__(self, root: Path):
        self.home = root / "home"
        self.config = root / "config"
        (self.home / ".claude" / "projects").mkdir(parents=True)
        (self.config / "staff.d").mkdir(parents=True)
        self.settings = self.home / ".claude" / "settings.json"
        self.settings.write_text('{"remoteControlAtStartup": true}\n')  # claudestra requires it (DESIGN.md §7.1)

    @property
    def projects(self) -> Path:
        return self.home / ".claude" / "projects"

    def folder(self, rel: str) -> Path:
        p = self.home / rel
        p.mkdir(parents=True, exist_ok=True)
        return p

    def transcript(
        self, sid: str, folder: Path, records: list[dict] | None = None, slug_name: str | None = None
    ) -> Path:
        d = self.projects / (slug_name or slug(folder))
        d.mkdir(parents=True, exist_ok=True)
        t = d / f"{sid}.jsonl"
        recs = (
            records
            if records is not None
            else [
                {
                    "type": "user",
                    "uuid": f"{sid[:8]}-u1",
                    "sessionId": sid,
                    "cwd": str(folder),
                    "origin": {"kind": "human"},
                    "message": {"content": "hello"},
                },
                {"type": "agent-name", "agentName": f"name-{sid[:4]}", "sessionId": sid},
            ]
        )
        t.write_text("".join(json.dumps(r) + "\n" for r in recs))
        return t

    def staff_file(self, sid: str, name: str, folders: dict[str, str], extra: str = "") -> Path:
        f = self.config / "staff.d" / f"{sid}.yaml"
        f.write_text(
            "\n".join([f'name: "{name}"', "folder:", *(f"  {h}: {p}" for h, p in folders.items())])
            + "\ndescription: test staffer\n"
            + extra
        )
        return f

    def trust(self, text: str) -> None:
        (self.config / "trust.yaml").write_text(text)

    def fake_proc(self, chain: list[tuple[int, int, str, str]]) -> Path:
        """A /proc holding (pid, ppid, comm, exe) for each process, from the caller upwards."""
        root = self.home / "proc"
        for pid, ppid, comm, exe in chain:
            d = root / str(pid)
            d.mkdir(parents=True)
            (d / "stat").write_text(f"{pid} ({comm}) S {ppid} " + " ".join(["0"] * 17) + f" {1000 + pid} 0\n")
            (d / "comm").write_text(comm + "\n")
            (d / "exe").symlink_to(exe)
        return root

    def setup(self) -> tuple[ClaudeFS, Trust, Model]:
        fs = ClaudeFS(self.home, proc=self.home / "proc")
        t = load(HOST, self.home, self.config)
        return fs, t, build(fs, t, Machine(HOST, None, self.home))

    def acting(self, subject: Caller, scopes: dict[str, str] | None = None, **hooks) -> Context:
        """A context acting as `subject` on this machine, as trust.yaml describes it with `scopes`."""
        sessions = "".join(f"  {sid}:\n    scope: {sc}\n" for sid, sc in (scopes or {}).items())
        self.trust(
            f"machines:\n  {HERE}:\n    home: {self.home}\n    machine_id: {portable.machine_id()}\n"
            + (f"sessions:\n{sessions}" if sessions else "")
        )
        return Context.for_test(self.home, self.config, subject, **hooks)

    def cli_args(self) -> list[str]:
        return ["--home", str(self.home), "--config", str(self.config)]


def aged(p: Path, seconds: int = 3600) -> Path:
    """Make a file look untouched for a while, past the recent-write guard."""
    st = p.stat()
    os.utime(p, (st.st_atime - seconds, st.st_mtime - seconds))
    return p


def far_side(
    tmp_path: Path, ssh: str | None = "stand-in", machine_id: str | None = None
) -> tuple[transfer.LocalTransport, dict[str, MachineConf], Path]:
    """A second home standing in for the other machine. The helper reports this machine's real hostname
    and derived ID, so the stand-in takes them, unless `machine_id` says otherwise."""
    far_home = tmp_path / "far"
    (far_home / ".claude" / "projects").mkdir(parents=True)
    name = socket.gethostname()
    conf = MachineConf(name, Path("/"), ssh, machine_id or portable.machine_id(), [])
    return transfer.LocalTransport(name, far_home), {name.lower(): conf}, far_home


@pytest.fixture
def home(tmp_path: Path) -> Home:
    return Home(tmp_path)


@pytest.fixture(autouse=True)
def isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """claudestra's log, lock, backups and staging go into the temporary folder, never ~/.local or ~/.cache."""
    monkeypatch.setattr(common, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(transfer, "STAGING", tmp_path / "staging")


@pytest.fixture(autouse=True)
def no_context_left():
    """Each test starts with no claudestra context, and leaves none behind."""
    Context.reset()
    yield
    Context.reset()


# --- the command line, as the CLI tests drive it -------------------------------------------------


def run(*args, **kwargs):
    """One command, as one process would run it: with a context of its own."""
    Context.reset()
    return CliRunner().invoke(*args, **kwargs)


class Answer:
    def __init__(self, value):
        self.value = value

    def ask(self):
        return self.value


@pytest.fixture
def at_terminal(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ui, "interactive", lambda: True)


@pytest.fixture
def as_him(home: Home, monkeypatch: pytest.MonkeyPatch):
    """This machine described in the fixture's trust.yaml, and the caller taken to be the user."""
    home.trust(f"machines:\n  {HERE}:\n    home: {home.home}\n    machine_id: {portable.machine_id()}\n")
    monkeypatch.setattr(context_mod, "identify", lambda *a, **k: Caller("human"))
    # The tests may themselves run under Claude; the user at a terminal has no Claude in the chain.
    monkeypatch.setattr(context_mod, "claude_chain", lambda *a, **k: [])
