"""`claudestra setup`, the first-run walk-through, with questionary answered by stand-ins; and the
`preferences` command. Everything it installs goes into the fixture home: the login unit and systemctl are
conftest's stand-ins, and the XDG folders are the fixture home's."""

from __future__ import annotations

from pathlib import Path

import pytest

from claudestra import trust as trust_mod
from claudestra.caller import Caller
from claudestra.cli import app, setup, ui
from claudestra.context import Context
from claudestra.ops import completion, guard, unit
from claudestra.ops import preferences as prefs

from conftest import HERE, A, Answer, Home, run


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """The user at a terminal in zsh, with claude on PATH, answering every question with `answers`."""
    monkeypatch.setattr(ui, "interactive", lambda: True)
    monkeypatch.setattr(setup, "interactive", lambda: True)
    monkeypatch.setattr(guard, "MANAGED", tmp_path / "etc")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    monkeypatch.setattr(unit.shutil, "which", lambda name: f"/opt/bin/{name}")
    answers: dict[str, object] = {"confirm": True, "text": "", "select": None}
    asked: list[str] = []

    def ask(kind):
        def stand_in(message, *a, choices=None, **k):
            asked.append(message)
            v = answers[kind]
            v = v(message) if callable(v) else v
            if v is None and choices:  # the first choice
                v = choices[0].value
            return Answer(v)

        return stand_in

    for kind in ("confirm", "text", "select"):
        monkeypatch.setattr(ui.questionary, kind, ask(kind))  # one questionary module, whoever imports it
    answers["asked"] = asked
    return answers


def described(home: Home, extra: str = "") -> None:
    """This machine as trust.yaml describes it (conftest's as_him), with `extra` added under it."""
    home.trust((home.config / "trust.yaml").read_text() + extra)


def test_setup_needs_a_terminal(home: Home, as_him):
    r = run(app, [*home.cli_args(), "setup"])
    assert r.exit_code == 1 and "asks its questions at a terminal" in r.output


def test_setup_is_the_users(home: Home, as_him, terminal, monkeypatch: pytest.MonkeyPatch):
    from claudestra import context as context_mod

    monkeypatch.setattr(context_mod, "identify", lambda *a, **k: Caller("unscoped", A, "x", 1))
    r = run(app, ["setup"])  # no test options, which a session may not give
    assert r.exit_code == 1 and "setup is the user's" in r.output


def test_setup_walks_every_step_and_installs_into_the_fixture(home: Home, as_him, terminal, no_real_login_unit):
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    terminal["select"] = lambda message: A if message.startswith("Which session manages") else None
    r = run(app, [*home.cli_args(), "setup"])
    assert r.exit_code == 0, r.output
    t = trust_mod.load(HERE, home.home, home.config)
    assert t.scope(A) == "device" and t.autostart(HERE) == [A]
    assert not guard.missing(Context.current().fs, home.config)
    assert unit.unit_path().is_file() and ["systemctl", "--user", "enable", unit.UNIT] in no_real_login_unit.ran
    assert completion.installed("zsh", home.home) and (home.home / ".zshrc").is_file()
    assert all(v is not None for v in prefs.load(home.config).values())
    assert "setup has done what it can" in r.output
    # Run again, everything is done and nothing is asked but whether to go on.
    terminal["asked"].clear()
    r = run(app, [*home.cli_args(), "setup"])
    assert r.exit_code == 0 and "to do" not in r.output and terminal["asked"] == []


def test_setup_dry_run_changes_nothing(home: Home, as_him, terminal, no_real_login_unit):
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    described(home, f"    autostart:\n      - {A}\n")
    before = (home.config / "trust.yaml").read_text()
    settings = home.settings.read_text()
    terminal["select"] = lambda message: "" if message.startswith("Which session manages") else None
    r = run(app, [*home.cli_args(), "setup", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert r.output.count("dry run; nothing changed") >= 3
    assert (home.config / "trust.yaml").read_text() == before and home.settings.read_text() == settings
    assert not unit.unit_path().exists() and no_real_login_unit.ran == []
    assert not (home.home / ".zshrc").exists() and not prefs.path(home.config).exists()


def test_setup_goes_on_past_a_declined_step(home: Home, as_him, terminal):
    terminal["confirm"] = False  # every "Go ahead?" answered no
    terminal["select"] = lambda message: "" if message.startswith("Which session manages") else None
    r = run(app, [*home.cli_args(), "setup"])
    assert r.exit_code == 0 and "setup has done what it can" in r.output
    assert guard.missing(Context.current().fs, home.config)


def test_setup_reports_a_machine_trust_describes_differently(home: Home, as_him, terminal):
    home.trust(f"machines:\n  {HERE}:\n    home: {home.home}\n    machine_id: not-this-one\n")
    terminal["select"] = lambda message: "" if message.startswith("Which session manages") else None
    r = run(app, [*home.cli_args(), "setup"])
    assert "fix it with `claudestra trust machine remove` and `add`" in r.output


def test_setup_spawning_a_manager_needs_claude(home: Home, as_him, terminal, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(setup.shutil, "which", lambda name: None)
    terminal["select"] = lambda message: "new" if message.startswith("Which session manages") else None
    r = run(app, [*home.cli_args(), "setup", "--dry-run"])
    assert "claude is not on PATH, so no session can be spawned" in r.output


def test_setup_describes_a_fresh_machine_and_grants_its_manager(home: Home, as_him, terminal, no_real_login_unit):
    """With no trust.yaml, the first step describes this machine, and the later steps, which need it
    described, then run: the device-scope grant, autostart and the login unit."""
    (home.config / "trust.yaml").unlink()
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    terminal["text"] = "u@here"
    terminal["select"] = lambda message: A if message.startswith("Which session manages") else None
    r = run(app, [*home.cli_args(), "setup"])
    assert r.exit_code == 0, r.output
    assert "refused" not in r.output
    t = trust_mod.load(HERE, home.home, home.config)
    assert t.machines[HERE.lower()].ssh == "u@here"
    assert t.scope(A) == "device" and t.autostart(HERE) == [A]
    assert unit.unit_path().is_file() and ["systemctl", "--user", "enable", unit.UNIT] in no_real_login_unit.ran


# --- preferences ----------------------------------------------------------------------------------------


def test_preferences_show_set_and_refuse(home: Home, as_him):
    key = next(iter(prefs.PREFERENCES))
    value = next(iter(prefs.PREFERENCES[key].choices))
    r = run(app, [*home.cli_args(), "preferences"])
    assert r.exit_code == 0 and f"{key}: -" in r.output and "not chosen" in r.output
    r = run(app, [*home.cli_args(), "preferences", key, value, "-y"])
    assert r.exit_code == 0, r.output
    assert prefs.load(home.config)[key] == value
    r = run(app, [*home.cli_args(), "preferences", "--json"])
    assert r.exit_code == 0 and f'"value": "{value}"' in r.output
    r = run(app, [*home.cli_args(), "preferences", "no-such", value])
    assert r.exit_code == 1 and "no preference 'no-such'" in r.output
    r = run(app, [*home.cli_args(), "preferences", key, "no-such-value", "-y"])
    assert r.exit_code == 1 and "not 'no-such-value'" in r.output


def test_preferences_are_set_by_the_user_alone(home: Home):
    from claudestra.actions.preferences import SetPreference, ShowPreferences
    from claudestra.caller import Refused

    key = next(iter(prefs.PREFERENCES))
    value = next(iter(prefs.PREFERENCES[key].choices))
    home.acting(Caller("unscoped", A, "x", 1))
    with pytest.raises(Refused):
        SetPreference(key, value).perform()
    assert prefs.load(home.config)[key] is None
    assert ShowPreferences().perform()[key] is None  # anyone may read them


def test_a_broken_preferences_file_is_reported_and_written_afresh(home: Home, as_him):
    key = next(iter(prefs.PREFERENCES))
    value = next(iter(prefs.PREFERENCES[key].choices))
    broken = prefs.path(home.config)
    broken.write_text("{not: [closed")
    r = run(app, [*home.cli_args(), "check"])
    assert "cannot be read" in r.output
    r = run(app, [*home.cli_args(), "preferences", key, value, "-y"])
    assert r.exit_code == 0, r.output
    assert prefs.load(home.config)[key] == value
    assert broken.with_name(broken.name + ".unreadable").read_text() == "{not: [closed"
    broken.write_text(f"{key}: nonsense\nextra: 1\n")
    found = prefs.problems(home.config)
    assert f"{broken.name}: 'extra' is not a preference" in found
    assert any("'nonsense'" in p and "reads as not chosen" in p for p in found)
    assert prefs.load(home.config)[key] is None
