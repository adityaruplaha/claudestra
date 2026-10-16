"""The login unit: what it says, installing and removing it, and the doctor noticing one that differs.

conftest.no_real_login_unit puts the unit in the temporary folder and records systemctl instead of running
it; every test here relies on that, and asserts it where it writes."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from claudestra import checks
from claudestra.actions.install_unit import InstallUnit
from claudestra.caller import Caller, Refused
from claudestra.cli import app
from claudestra.model import Machine
from claudestra.ops import unit
from claudestra.ops.unit import claude_path as real_claude_path  # both taken before conftest replaces them
from claudestra.ops.unit import unit_path as real_unit_path

from conftest import HERE, HOST, HUMAN, A, Home, run

CLAUDESTRA, CLAUDE = "/opt/bin/claudestra", "/opt/bin/claude"


@pytest.fixture
def on_path(monkeypatch: pytest.MonkeyPatch):
    """claudestra and claude installed outside the package, as `uv tool install` and Claude Code put them."""
    found = {"claudestra": CLAUDESTRA, "claude": CLAUDE, "uv": "/opt/bin/uv"}
    monkeypatch.setattr(unit.shutil, "which", lambda name: found.get(name))
    monkeypatch.setattr(unit, "claude_path", real_claude_path)  # found through the stubbed PATH, as installed
    return found


@pytest.fixture
def stand_in(no_real_login_unit, tmp_path: Path) -> Path:
    p = unit.unit_path()
    assert p.is_relative_to(tmp_path) and not p.is_relative_to(Path.home() / ".config")
    return p


# --- what the unit says --------------------------------------------------------------------------------


def test_the_unit_records_the_exact_paths_and_runs_autostart(on_path):
    text = unit.expected()
    assert f"ExecStart={CLAUDESTRA} autostart --claude {CLAUDE}\n" in text
    assert [ln for ln in text.splitlines() if ln.startswith("ExecStart")] == [
        f"ExecStart={CLAUDESTRA} autostart --claude {CLAUDE}"
    ]
    assert "Type=oneshot" in text and "KillMode=process" in text and "WantedBy=graphical-session.target" in text


def test_paths_with_spaces_are_quoted():
    assert "ExecStart='/a b/claudestra' autostart --claude '/c d/claude'" in unit.unit_text(
        ["/a b/claudestra"], "/c d/claude"
    )


def test_claudestra_from_the_package_runs_through_uv(monkeypatch: pytest.MonkeyPatch):
    """The package's own .venv is rebuilt per machine, so the unit runs the package through uv instead."""
    inside = str(unit.PACKAGE / ".venv" / "bin" / "claudestra")
    monkeypatch.setattr(unit.shutil, "which", lambda name: {"claudestra": inside, "uv": "/opt/bin/uv"}.get(name))
    assert unit.cam_command() == ["/opt/bin/uv", "run", "--quiet", "--project", str(unit.PACKAGE), "claudestra"]
    monkeypatch.setattr(unit.shutil, "which", lambda name: None)
    assert unit.cam_command()[0] == str(Path.home() / ".local" / "bin" / "uv")


def test_claude_off_path_refuses(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(unit, "claude_path", real_claude_path)
    monkeypatch.setattr(unit.shutil, "which", lambda name: None)
    with pytest.raises(Refused, match="claude is not on PATH"):
        unit.expected()


def test_the_unit_lives_in_the_user_systemd_folder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Only the path is computed here; nothing is read or written there."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert real_unit_path() == tmp_path / "xdg" / "systemd" / "user" / unit.UNIT
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert real_unit_path() == Path.home() / ".config" / "systemd" / "user" / unit.UNIT


# --- install and uninstall -----------------------------------------------------------------------------


def test_install_writes_and_enables_it(on_path, stand_in: Path, no_real_login_unit):
    dry = unit.install(True)
    assert not stand_in.exists() and no_real_login_unit.ran == []
    assert dry[-1].startswith("would run: systemctl --user daemon-reload")
    out = unit.install(False)
    assert stand_in.read_text() == unit.expected()
    assert no_real_login_unit.ran == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", unit.UNIT],
    ]
    assert f"systemctl --user enable {unit.UNIT}: ok" in out
    assert "already installed and current" in unit.install(True)


def test_install_reports_a_failing_systemctl(on_path, stand_in: Path, no_real_login_unit, monkeypatch):
    monkeypatch.setattr(
        no_real_login_unit, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 1, "", "no user bus\n")
    )
    out = unit.install(False)
    assert "systemctl --user daemon-reload: no user bus" in out and stand_in.is_file()


def test_uninstall_disables_and_removes_it(on_path, stand_in: Path, no_real_login_unit):
    assert unit.uninstall(False) == [] and no_real_login_unit.ran == []  # nothing installed: nothing to do
    unit.install(False)
    no_real_login_unit.ran.clear()
    assert unit.uninstall(True) == [f"would run: systemctl --user disable {unit.UNIT}", f"would remove {stand_in}"]
    assert stand_in.exists() and no_real_login_unit.ran == []
    out = unit.uninstall(False)
    assert not stand_in.exists() and out[-1] == f"removed {stand_in}"
    assert no_real_login_unit.ran == [
        ["systemctl", "--user", "disable", unit.UNIT],
        ["systemctl", "--user", "daemon-reload"],
    ]


def test_install_login_unit_is_the_users_alone(home: Home, on_path, stand_in: Path):
    home.acting(Caller("unscoped", A, "x", 1))
    with pytest.raises(Refused):
        InstallUnit().perform()
    assert not stand_in.exists()


def test_install_login_unit_action_prints_what_systemctl_did(home: Home, on_path, stand_in: Path):
    home.acting(HUMAN)
    out = InstallUnit().perform()
    assert stand_in.read_text() == unit.expected()
    assert out[0] == "systemctl --user daemon-reload: ok" and out[-1].startswith("it runs at the next login")


def test_install_login_unit_from_the_command_line(home: Home, as_him, on_path, stand_in: Path):
    r = run(app, [*home.cli_args(), "install", "login-unit", "-y"])
    assert r.exit_code == 0, r.output
    assert f"ExecStart={CLAUDESTRA} autostart --claude {CLAUDE}" in stand_in.read_text()


# --- the doctor's login-unit check ---------------------------------------------------------------------


def login_unit(home: Home, autostart: bool = True) -> checks.Result:
    home.trust(
        f"machines:\n  {HOST}:\n    home: {home.home}\n    machine_id: id-1\n"
        + (f"    autostart:\n      - {A}\n" if autostart else "")
    )
    fs, t, _ = home.setup()
    return checks.run(fs, ["login-unit"], False, t, Machine(HOST, "id-1", home.home))[0]


def test_doctor_login_unit(home: Home, on_path, stand_in: Path, monkeypatch: pytest.MonkeyPatch):
    assert login_unit(home, autostart=False).status == checks.NA
    r = login_unit(home)
    assert r.status == checks.FAIL and "is not installed" in r.detail and "install login-unit" in r.detail
    unit.install(False)
    assert login_unit(home).status == checks.PASS
    stand_in.write_text(stand_in.read_text().replace(CLAUDE, "/old/claude"))  # claude has moved since
    r = login_unit(home)
    assert r.status == checks.FAIL and "differs from what claudestra would write" in r.detail
    monkeypatch.setattr(unit.shutil, "which", lambda name: None)
    r = login_unit(home)
    assert r.status == checks.FAIL and "claude is not on PATH" in r.detail


def test_doctor_login_unit_from_the_command_line(home: Home, as_him, on_path, stand_in: Path):
    home.trust((home.config / "trust.yaml").read_text() + f"    autostart:\n      - {A}\n")
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    r = run(app, [*home.cli_args(), "doctor", "login-unit"])
    assert r.exit_code != 0 and "is not installed" in r.output
    unit.install(False)
    r = run(app, [*home.cli_args(), "doctor", "login-unit"])
    assert r.exit_code == 0 and "installed and current" in r.output
