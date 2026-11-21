"""A staffer whose conversation is gone (audit's staff report, `gone` in staff list), and `claudestra staff
rotate`, which gives a staffer a new session and keeps its place on the staff."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest
import yaml

from claudestra import portable
from claudestra.caller import Caller, Refused
from claudestra.context import Context
from claudestra.ops import audit
from claudestra.ops import trash as trash_ops
from claudestra.runners import tmux as runner

from conftest import HERE, HUMAN, A, B, C, Home, aged


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake = tmp_path / "claude"
    fake.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {tmp_path}/argv\ntrap "exit 0" INT\nwhile :; do sleep 1; done\n')
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
    return (tmp / "argv").read_text().splitlines()


def staffer(sid: str):
    return Context.current().staffer(sid)


def trust_with(home: Home, scopes: dict[str, str], autostart: list[str]) -> None:
    sessions = "".join(f"  {sid}:\n    scope: {sc}\n" for sid, sc in scopes.items())
    auto = "    autostart:\n" + "".join(f"      - {s}\n" for s in autostart) if autostart else ""
    home.trust(
        f"machines:\n  {HERE}:\n    home: {home.home}\n    machine_id: {portable.machine_id()}\n{auto}"
        + (f"sessions:\n{sessions}" if sessions else "")
    )
    Context.current().refresh()


def test_a_staffer_for_this_machine_alone_with_no_transcript_is_lost(home: Home):
    """Lost: a folder here and on no other machine, no transcript, nothing running it. One that names another
    machine may live there, and one with a transcript is not lost."""
    home.folder("w")
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "alive", {HERE: "~/w"})
    home.staff_file(B, "dead", {HERE: "~/w"})
    home.staff_file(C, "visitor", {HERE: "~/w", "elsewhere": "~/w"})
    c = home.acting(HUMAN)
    assert [sf.session for sf in c.model.lost_staff] == [B]
    [error] = audit.staff(c.fs, c.model)
    assert error.subject == B and 'staff rotate "dead"' in error.detail and error.fix() is None


def test_a_manager_rotates_a_lost_specialist_with_its_staff_entry_and_brief(home: Home, server):
    socket, tmp, claude = server
    top = home.folder("top")
    home.transcript(A, top)
    home.staff_file(A, "mgr", {HERE: "~/top"})
    home.folder("top/sub")
    old = home.staff_file(B, "spec", {HERE: "~/top/sub"})
    text = old.read_text()
    c = home.acting(HUMAN, {A: "folder"})
    c._subject = Caller("folder", A, "mgr", 1, folder=top)
    with pytest.raises(Refused, match="--prompt"):  # a session gives the brief
        staffer(B).rotate(claude, socket=socket, reason="r").perform()
    r = staffer(B).rotate(claude, "pick up the tests", socket=socket, reason="r")
    assert "started" in r.perform()
    new = home.config / "staff.d" / f"{r.new}.yaml"
    written = yaml.safe_load(new.read_text())
    assert not old.exists() and {k: v for k, v in written.items() if k != "history"} == yaml.safe_load(text)
    [h] = written["history"]
    assert h["session"] == B and h["reason"] == "r" and "T" in h["rotated"]  # an exact ISO time
    prompt = "\n".join(argv(tmp)[6:])  # after --session-id, --name and --remote-control
    assert f"You are spec, a staffer claudestra has rotated: you replace session {B}" in prompt
    assert "Claude Code deleted" in prompt and "answer to mgr" in prompt and prompt.endswith("pick up the tests")


def test_a_stopped_staffer_with_a_transcript_goes_to_the_trash(home: Home, server):
    socket, _, claude = server
    w = home.folder("w")
    aged(home.transcript(A, w))
    home.staff_file(A, "s", {HERE: "~/w"})
    c = home.acting(HUMAN)
    r = staffer(A).rotate(claude, socket=socket, reason="r")
    r.perform()
    assert A not in c.model.sessions and c.trust.named("s").session == r.new
    [(entry, mf)] = trash_ops.entries(c.fs)
    assert mf["session_id"] == A and mf["reason"] == f"rotated to {r.new}"


def test_rotating_a_manager_moves_its_scope_and_autostart_and_its_staffers_follow(home: Home, server):
    socket, _, claude = server
    top = home.folder("top")
    home.staff_file(A, "mgr", {HERE: "~/top"})  # lost
    home.folder("top/sub")
    home.transcript(B, home.folder("top/sub"))
    home.staff_file(B, "spec", {HERE: "~/top/sub"})
    dev = "dddddddd-4444-4444-8444-444444444444"
    home.transcript(dev, home.folder("d"))
    home.staff_file(dev, "dev", {HERE: "~/d"})
    c = home.acting(HUMAN)
    trust_with(home, {A: "folder", dev: "device"}, [A])
    c._subject = Caller("device", dev, "dev", 1)
    with pytest.raises(Refused, match="may not rotate"):  # a device scope, over a manager
        staffer(A).rotate(claude, "b", socket=socket, reason="r").perform()
    c._subject = Caller("folder", A, "mgr", 1, folder=top)
    with pytest.raises(Refused, match="itself"):
        staffer(A).rotate(claude, "b", socket=socket, reason="r").perform()
    c._subject = HUMAN
    r = staffer(A).rotate(claude, socket=socket, reason="r")
    r.perform()
    assert c.trust.scope(r.new) == "folder" and c.trust.autostart(HERE) == [r.new] and A not in c.trust.scopes
    assert [m.session for m in c.trust.managers_over(c.trust.staff_file(B))] == [r.new]


def test_a_specialist_that_starts_at_login_is_the_users_to_rotate(home: Home, server):
    socket, _, claude = server
    top = home.folder("top")
    home.transcript(A, top)
    home.staff_file(A, "mgr", {HERE: "~/top"})
    home.folder("top/sub")
    home.staff_file(B, "spec", {HERE: "~/top/sub"})
    c = home.acting(HUMAN)
    trust_with(home, {A: "folder"}, [B])
    c._subject = Caller("folder", A, "mgr", 1, folder=top)
    with pytest.raises(Refused, match="trust.yaml.*is for the user"):
        staffer(B).rotate(claude, "b", socket=socket, reason="r").perform()


def test_a_failed_start_puts_everything_back(home: Home, server):
    socket, _, _ = server
    w = home.folder("w")
    tr = aged(home.transcript(A, w))
    old = home.staff_file(A, "s", {HERE: "~/w"})
    c = home.acting(HUMAN)
    trust_with(home, {A: "folder"}, [A])
    before = (home.config / "trust.yaml").read_text()
    r = staffer(A).rotate("/nowhere/claude", socket=socket, reason="r")
    with pytest.raises(Refused, match="claude is not at"):
        r.perform()
    assert old.exists() and not (home.config / "staff.d" / f"{r.new}.yaml").exists()
    assert (home.config / "trust.yaml").read_text() == before and tr.exists()
    assert not trash_ops.entries(c.fs)


def test_a_running_staffer_or_one_that_may_live_elsewhere_is_refused(home: Home, server):
    socket, _, claude = server
    home.folder("w")
    home.staff_file(C, "visitor", {HERE: "~/w", "elsewhere": "~/w"})
    home.acting(HUMAN)
    with pytest.raises(Refused, match="may live on elsewhere"):
        staffer(C).rotate(claude, socket=socket, reason="r").perform()
