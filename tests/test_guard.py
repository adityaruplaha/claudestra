"""The guard that keeps sessions out of claudestra's config: the deny rules, the hook script and what it
refuses, the install into the user's settings by anyone, the managed drop-in, and `doctor guard`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from claudestra import context as context_mod
from claudestra.caller import Caller
from claudestra.cli import app
from claudestra.ops import guard

from conftest import B, Home, run


@pytest.fixture(autouse=True)
def no_managed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Managed settings looked for in the temporary folder, never /etc."""
    monkeypatch.setattr(guard, "MANAGED", tmp_path / "etc")


def settings(home: Home) -> Path:
    return home.home / ".claude" / "settings.json"


def test_the_rules_name_the_default_folder_and_any_other():
    assert guard.rules(Path("/home/u/.config/claudestra")) == [
        "Read(//home/*/.config/claudestra/**)",
        "Edit(//home/*/.config/claudestra/**)",
    ]
    assert guard.rules(Path("/srv/cfg"))[2:] == ["Read(//srv/cfg/**)", "Edit(//srv/cfg/**)"]
    assert len(guard.rules(Path("/home/u/x/.config/claudestra"))) == 4  # * does not cross a /


def test_install_adds_the_guard_and_keeps_the_rest(home: Home, as_him):
    theirs = {"matcher": "Bash", "hooks": [{"type": "command", "command": "their-hook"}]}
    settings(home).write_text(
        json.dumps({"model": "opus", "permissions": {"deny": ["Bash(rm *)"]}, "hooks": {"PreToolUse": [theirs]}})
    )
    before = settings(home).read_text()
    r = run(app, [*home.cli_args(), "install", "guard", "--dry-run"])
    assert r.exit_code == 0 and "would add to" in r.output and settings(home).read_text() == before
    assert not (home.config / "guard.py").exists()
    assert "install guard" in run(app, [*home.cli_args(), "doctor", "guard"]).output
    assert run(app, [*home.cli_args(), "install", "guard", "-y"]).exit_code == 0
    data = json.loads(settings(home).read_text())
    assert data["model"] == "opus" and data["permissions"]["deny"] == ["Bash(rm *)", *guard.rules(home.config)]
    assert data["hooks"]["PreToolUse"] == [theirs, guard.hook_entry(home.config)]
    assert "sandbox" not in data  # the sandbox is the user's to turn on
    assert (home.config / "guard.py").is_file()
    assert "in place" in run(app, [*home.cli_args(), "install", "guard", "-y"]).output
    assert "kept out of the config" in run(app, [*home.cli_args(), "doctor", "guard"]).output


def test_a_changed_guard_is_written_again(home: Home, as_him):
    run(app, [*home.cli_args(), "install", "guard", "-y"])
    (home.config / "guard.py").write_text("# gutted\n")
    assert "guard.py as claudestra writes it" in run(app, [*home.cli_args(), "doctor", "guard"]).output
    r = run(app, [*home.cli_args(), "install", "guard", "-y"])
    assert r.exit_code == 0 and (home.config / "guard.py").read_text() == guard.GUARD_SOURCE


def test_a_session_may_install_it(home: Home, as_him, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(context_mod, "identify", lambda *a, **k: Caller("unscoped", B, "x", 1))
    r = run(app, [*home.cli_args(), "install", "guard", "-y"])
    assert r.exit_code == 0 and json.loads(settings(home).read_text())["permissions"]["deny"]


def test_a_sandbox_already_on_hides_the_folder_but_not_from_claudestra(home: Home, as_him):
    settings(home).write_text(json.dumps({"sandbox": {"enabled": True}}))
    assert run(app, [*home.cli_args(), "install", "guard", "-y"]).exit_code == 0
    sandbox = json.loads(settings(home).read_text())["sandbox"]
    assert sandbox["filesystem"] == {"denyRead": [str(home.config)], "denyWrite": [str(home.config)]}
    assert sandbox["excludedCommands"] == ["claudestra *", "clost *"]


def test_a_settings_file_it_cannot_read_is_left_alone(home: Home, as_him):
    settings(home).write_text("{ not json")
    r = run(app, [*home.cli_args(), "install", "guard", "-y"])
    assert r.exit_code == 1 and "cannot read" in r.output and settings(home).read_text() == "{ not json"


def test_managed_prints_a_drop_in_and_doctor_counts_it(home: Home, as_him, tmp_path: Path):
    before = settings(home).read_text()
    r = run(app, [*home.cli_args(), "install", "guard", "--managed"])
    assert r.exit_code == 0 and "sudo install" in r.output and settings(home).read_text() == before
    fs = home.setup()[0]
    (home.config / "guard.py").write_text(guard.GUARD_SOURCE)
    drop_in = tmp_path / "etc" / "managed-settings.d" / "claudestra.json"
    drop_in.parent.mkdir(parents=True)
    hooks = {"PreToolUse": [guard.hook_entry(home.config)]}
    drop_in.write_text(json.dumps({"permissions": {"deny": guard.rules(home.config)}, "hooks": hooks}))
    assert guard.missing(fs, home.config) == []


# --- the hook itself ---------------------------------------------------------------------------------


@pytest.fixture
def hook(home: Home):
    """The guard where claudestra's config usually is, ~/.config/claudestra, in the fixture's home."""
    cfg = home.home / ".config" / "claudestra"
    cfg.mkdir(parents=True)
    script = cfg / "guard.py"
    script.write_text(guard.GUARD_SOURCE)

    def call(tool: str | None, tool_input: dict | None = None, raw: str | None = None, cwd: Path | None = None) -> int:
        stdin = (
            raw
            if raw is not None
            else json.dumps({"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd or home.home)})
        )
        cmd = [sys.executable, "-I", "-S", str(script)]
        env = {**os.environ, "HOME": str(home.home), "XDG_CONFIG_HOME": str(home.home / ".config")}
        env.pop("CLAUDE_CONFIG_DIR", None)
        return subprocess.run(cmd, input=stdin, capture_output=True, text=True, env=env).returncode

    return call


def test_the_hook_refuses_what_names_the_config(home: Home, hook):
    cfg = home.home / ".config" / "claudestra"
    assert hook("Bash", {"command": f"cat {cfg}/trust.yaml"}) == 2
    assert hook("Bash", {"command": f"python3 -c \"open('{cfg}/staff.d/x.yaml', 'w')\""}) == 2
    assert hook("Bash", {"command": 'echo x >> "$XDG_CONFIG_HOME/claudestra/trust.yaml"'}) == 2
    assert hook("Bash", {"command": "echo x>${HOME}/.config/claudestra/trust.yaml"}) == 2
    assert hook("Bash", {"command": "cp a ~/.config/claudestra/"}) == 2
    assert hook("Bash", {"command": "cat claudestra/trust.yaml"}, cwd=home.home / ".config") == 2
    assert hook("Bash", {"command": "ls"}, cwd=cfg) == 2
    assert hook("Read", {"file_path": str(cfg / "trust.yaml")}) == 2
    assert hook("Grep", {"pattern": "x", "path": str(cfg)}) == 2


def test_the_hook_lets_through_what_only_mentions_it(home: Home, hook):
    repo = home.home / "Documents" / "Tools" / "claudestra"
    assert hook("Bash", {"command": "grep -rn '.config/claudestra' DESIGN.md"}, cwd=repo) == 0
    assert hook("Bash", {"command": "cat .config/claudestra/trust.yaml"}) == 2  # from the home folder, it is the config
    assert hook("Bash", {"command": "cd ~/Documents/Tools/claudestra && uv run pytest"}) == 0
    assert hook("Bash", {"command": "claudestra trust show"}) == 0
    assert hook("Bash", {"command": "ls ~/.config"}) == 0
    assert hook("Read", {"file_path": str(home.home / "notes.md")}) == 0


def test_the_hook_refuses_an_edit_that_removes_it_from_the_settings(home: Home, hook):
    s, g = str(settings(home)), str(home.home / ".config" / "claudestra" / "guard.py")
    assert hook("Edit", {"file_path": s, "old_string": f'"command": "python {g}"', "new_string": ""}) == 2
    assert hook("Edit", {"file_path": s, "old_string": '"model": "opus"', "new_string": '"model": "sonnet"'}) == 0
    assert hook("Write", {"file_path": s, "content": "{}"}) == 2
    assert hook("Write", {"file_path": s, "content": json.dumps({"x": g})}) == 0


def test_the_hook_fails_open_on_input_it_cannot_read(hook):
    assert hook(None, raw="not json") == 0


def test_uninstall_takes_out_what_claudestra_added_and_keeps_the_rest(
    home: Home, as_him, monkeypatch, no_real_login_unit
):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.delenv("ZDOTDIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(home.home / ".local" / "share"))
    rc = home.home / ".zshrc"
    rc.write_text("export A=1\n")
    settings(home).write_text(
        json.dumps({"model": "opus", "permissions": {"deny": ["Bash(rm *)"]}, "remoteControlAtStartup": True})
    )
    assert run(app, [*home.cli_args(), "install", "guard", "-y"]).exit_code == 0
    assert run(app, [*home.cli_args(), "install", "completion", "zsh", "-y"]).exit_code == 0
    assert "claudestra" in rc.read_text()
    from claudestra.ops import unit

    stand_in = unit.unit_path()  # the test's own, never the user's (conftest.no_real_login_unit)
    assert not stand_in.is_relative_to(Path.home() / ".config")
    stand_in.parent.mkdir(parents=True)
    stand_in.write_text("[Unit]\n")
    r = run(app, [*home.cli_args(), "uninstall", "-y"])
    assert r.exit_code == 0, r.output
    assert not stand_in.exists() and ["systemctl", "--user", "disable", unit.UNIT] in no_real_login_unit.ran
    data = json.loads(settings(home).read_text())
    assert data["model"] == "opus" and data["permissions"]["deny"] == ["Bash(rm *)"]
    assert data["hooks"]["PreToolUse"] == [] and data["remoteControlAtStartup"] is True
    assert not (home.config / "guard.py").exists() and rc.read_text() == "export A=1\n"
