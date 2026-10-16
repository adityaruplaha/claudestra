"""`claudestra session spawn`: a new session begun under an ID claudestra chooses, with its name and first prompt,
hired with --staff; who may spawn where."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest
import yaml

from claudestra.actions.spawn import Spawn
from claudestra.caller import Caller, Refused
from claudestra.runners import tmux as runner

from conftest import HERE, HUMAN, A, Home


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake = tmp_path / "claude"
    fake.write_text(f'#!/bin/sh\necho "$@" > {tmp_path}/argv\ntrap "exit 0" INT\nwhile :; do sleep 1; done\n')
    fake.chmod(0o755)
    monkeypatch.setattr(runner, "STARTUP_WAIT", 1.0)
    socket = f"camtest-{uuid.uuid4().hex[:8]}"
    yield socket, tmp_path, str(fake)
    runner.Tmux(socket).server.cmd("kill-server")


def argv(tmp: Path) -> list[str]:
    for _ in range(50):
        if (tmp / "argv").exists():
            break
        time.sleep(0.1)
    return (tmp / "argv").read_text().split()


def test_it_begins_a_session_under_a_chosen_id_with_its_name_and_prompt(home: Home, server):
    socket, tmp, claude = server
    home.acting(HUMAN)
    s = Spawn(home.folder("w"), claude, "look", "helper", socket=socket)
    assert "started" in s.perform()
    assert argv(tmp) == ["--session-id", s.session.id, "--name", "helper", "--remote-control", "helper", "look"]
    w = runner.Tmux(socket).window(s.session.id)  # found by the ID it holds, and showing the name
    assert w and w.name == "helper" and w.session == s.session.id
    assert not list((home.config / "staff.d").iterdir())


def test_staff_hires_it_first_and_needs_a_name_a_description_and_a_brief(home: Home, server):
    socket, tmp, claude = server
    home.acting(HUMAN)
    with pytest.raises(Refused, match="--name"):
        Spawn(home.folder("w"), claude, "brief", staff=True, description="d", socket=socket).perform()
    with pytest.raises(Refused, match="--prompt"):
        Spawn(home.folder("w"), claude, None, "s", True, "d", socket).perform()
    with pytest.raises(Refused, match="add --staff"):
        Spawn(home.folder("w"), claude, "brief", "s", False, "d", socket).perform()
    s = Spawn(home.folder("w"), claude, "brief", "s", True, "works on w", socket)
    s.perform()
    staff = yaml.safe_load((home.config / "staff.d" / f"{s.session.id}.yaml").read_text())
    assert staff["name"] == "s" and staff["folder"] == {HERE: "~/w"} and staff["description"] == "works on w"


def test_a_failed_start_takes_the_staff_file_back(home: Home, server):
    socket, _, _ = server
    home.acting(HUMAN)
    s = Spawn(home.folder("w"), "/nowhere/claude", "brief", "s", True, "d", socket)
    with pytest.raises(Refused, match="claude is not at"):
        s.perform()
    assert not (home.config / "staff.d" / f"{s.session.id}.yaml").exists()


def test_who_may_spawn_where(home: Home, server):
    socket, _, claude = server
    top, loose = home.folder("top"), home.folder("loose")
    home.transcript(A, top)
    home.staff_file(A, "mgr", {HERE: "~/top"})
    mgr = Caller("folder", A, "mgr", 1, folder=top)
    dev = Caller("device", "eeeeeeee-5555-4555-8555-555555555555", "dev", 1)
    spec = Caller("unscoped", "ffffffff-6666-4666-8666-666666666666", "spec", 1)

    c = home.acting(HUMAN, {A: "folder", dev.session: "device"})

    def spawn(who: Caller, folder: Path, staff: bool = False) -> None:
        c._subject = who
        s = Spawn(folder, claude, "brief", f"n{uuid.uuid4().hex[:6]}", staff, "d", socket)
        s.check()
        s.authorize()

    spawn(mgr, home.folder("top/sub"), staff=True)  # inside its own folder
    with pytest.raises(Refused, match="may not spawn"):
        spawn(mgr, loose)
    spawn(dev, loose, staff=True)  # anywhere; no manager holds it
    with pytest.raises(Refused, match="'mgr' manages .*ask it by message"):  # its manager spawns there
        spawn(dev, home.folder("top/sub"))
    c._subject = dev
    with pytest.raises(Refused, match="always a staffer"):  # a session's spawn is always hired
        Spawn(loose, claude, "b", None, False, None, socket).check()
    with pytest.raises(Refused, match="may not spawn"):
        spawn(spec, loose)


def test_peek_shows_a_running_sessions_screen_and_wait_returns_once_it_is_done(home: Home, server):
    from claudestra.actions.peek import Peek
    from claudestra.actions.wait_idle import WaitIdle
    from claudestra.session import Session

    socket, _, claude = server
    home.acting(HUMAN)
    s = Spawn(home.folder("w"), claude, "look", "helper", socket=socket)
    s.perform()
    t = runner.Tmux(socket)
    t.run("send-keys", "-t", t.window(s.session.id).id, "echo hello-from-the-pane", "Enter")
    assert isinstance(Peek(s.session, 10, socket).perform(), list)
    with pytest.raises(Refused, match="not running in claudestra's tmux"):
        Peek(Session(A), 10, socket).perform()
    assert WaitIdle([Session(A)], 1).perform() == {A: "stopped"}  # a stopped session is done
