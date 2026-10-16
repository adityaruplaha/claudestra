"""Remote Control for every session, which claudestra requires: `doctor remote-control`, where Claude Code
reads the setting from, `enable-remote-control`, and `start` refusing without it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claudestra.checks import FAIL, PASS, check_remote_control
from claudestra.cli import app
from claudestra.model import Machine
from claudestra.ops import guard
from claudestra.ops import remote_control as rc

from conftest import HOST, A, Home, run


@pytest.fixture(autouse=True)
def no_managed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(guard, "MANAGED", tmp_path / "etc")


def doctor(home: Home):
    fs, trust, _ = home.setup()
    return check_remote_control(fs, False, trust, Machine(HOST, None, home.home))


def test_it_passes_when_the_user_turns_it_on(home: Home):
    r = doctor(home)
    assert r.status == PASS and "the user's settings" in r.detail


def test_it_fails_off_or_unset_and_says_how_to_turn_it_on(home: Home):
    home.settings.write_text(json.dumps({"remoteControlAtStartup": False}))
    r = doctor(home)
    assert r.status == FAIL and "turns it off" in r.detail and "enable-remote-control" in r.detail
    home.settings.write_text("{}")
    assert "Claude Code's default" in doctor(home).detail


def test_the_older_copy_counts_but_the_users_settings_come_first(home: Home):
    home.settings.write_text("{}")
    (home.home / ".claude.json").write_text(json.dumps({"remoteControlAtStartup": True}))
    assert doctor(home).status == PASS
    home.settings.write_text(json.dumps({"remoteControlAtStartup": False}))
    assert doctor(home).status == FAIL


def test_managed_settings_win_and_cannot_be_overridden(home: Home, tmp_path: Path, as_him):
    managed = tmp_path / "etc" / "managed-settings.json"
    managed.parent.mkdir(parents=True)
    managed.write_text(json.dumps({"remoteControlAtStartup": False}))
    assert "managed settings" in doctor(home).detail
    r = run(app, [*home.cli_args(), "enable-remote-control", "-y"])
    assert r.exit_code == 1 and "only whoever manages them" in r.output


def test_a_staffers_folder_can_turn_it_off_there(home: Home):
    folder = home.folder("work")
    home.staff_file(A, "w", {HOST: str(folder)})
    (folder / ".claude").mkdir()
    (folder / ".claude" / "settings.local.json").write_text(json.dumps({"remoteControlAtStartup": False}))
    r = doctor(home)
    assert r.status == FAIL and "settings.local.json turns it off" in r.detail and "propose" not in r.detail


def test_enable_sets_it_and_keeps_the_rest(home: Home, as_him):
    home.settings.write_text(json.dumps({"model": "opus", "remoteControlAtStartup": False}))
    r = run(app, [*home.cli_args(), "enable-remote-control", "--dry-run"])
    assert r.exit_code == 0 and "would set" in r.output and "false" in home.settings.read_text()
    assert run(app, [*home.cli_args(), "enable-remote-control", "-y"]).exit_code == 0
    assert json.loads(home.settings.read_text()) == {"model": "opus", "remoteControlAtStartup": True}
    assert "is on" in run(app, [*home.cli_args(), "enable-remote-control", "-y"]).output


def test_only_the_user_may_enable_it(home: Home, monkeypatch: pytest.MonkeyPatch):
    from claudestra import context as context_mod
    from claudestra.caller import Caller

    home.settings.write_text("{}")
    monkeypatch.setattr(context_mod, "identify", lambda *a, **k: Caller("unscoped", "b" * 8, "x", 1))
    r = run(app, [*home.cli_args(), "enable-remote-control", "-y"])
    assert r.exit_code == 1 and home.settings.read_text() == "{}"


def test_off_in_ignores_the_users_own_settings_seen_from_home(home: Home):
    home.settings.write_text(json.dumps({"remoteControlAtStartup": False}))
    assert rc.off_in(home.setup()[0], home.home) == []
