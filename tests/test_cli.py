"""The CLI: pickers, confirmation and the bare-`claudestra` menu with questionary answered by stand-ins
(there is no terminal under pytest), the preamble every changing command runs, and the output."""

from __future__ import annotations

import pytest

from claudestra import context as context_mod
from claudestra.caller import Caller
from claudestra.cli import app, ui
from claudestra.cli import base as app_mod

from conftest import A, Answer, B, Home, aged, run


def test_no_terminal_never_prompts(home: Home, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ui.questionary, "select", lambda *a, **k: pytest.fail("prompted without a terminal"))
    home.transcript(A, home.folder("w"))
    r = run(app, [*home.cli_args(), "show"])
    assert r.exit_code == 1 and "only asks at a terminal" in r.output


def test_picker_fills_a_missing_session(home: Home, at_terminal, monkeypatch: pytest.MonkeyPatch):
    home.transcript(A, home.folder("w"))
    home.transcript(B, home.folder("w"))
    seen = {}

    def select(message, choices, **kw):
        seen["values"] = [c.value for c in choices]
        return Answer(B)

    monkeypatch.setattr(ui.questionary, "select", select)
    r = run(app, [*home.cli_args(), "show", "--json"])
    assert r.exit_code == 0, r.output
    assert set(seen["values"]) == {A, B} and f'"session": "{B}"' in r.output


def test_menu_lists_commands_and_runs_the_chosen_one(home: Home, at_terminal, monkeypatch: pytest.MonkeyPatch):
    home.transcript(A, home.folder("w"))
    offered = {}

    def select(message, choices, **kw):
        offered["names"] = [c.value for c in choices]
        return Answer("audit")

    monkeypatch.setattr(app_mod.questionary, "select", select)
    r = run(app, home.cli_args())
    assert "two-homes" in r.output and {"ls", "move", "trash", "send", "purge"} <= set(offered["names"])
    assert "list" not in offered["names"]  # the hidden alias is not offered twice


def test_cancelled_picker_changes_nothing(home: Home, at_terminal, monkeypatch: pytest.MonkeyPatch):
    home.transcript(A, home.folder("w"))
    monkeypatch.setattr(ui.questionary, "select", lambda *a, **k: Answer(None))
    assert run(app, [*home.cli_args(), "show"]).exit_code == 130


def test_confirmation(home: Home, as_him, at_terminal, monkeypatch: pytest.MonkeyPatch):
    tr = aged(home.transcript(A, home.folder("w")))
    monkeypatch.setattr(ui.questionary, "confirm", lambda *a, **k: Answer(False))
    r = run(app, [*home.cli_args(), "rename", A, "new"])
    assert "nothing changed" in r.output and "new" not in tr.read_text()
    r = run(app, [*home.cli_args(), "rename", A, "new", "--dry-run"])
    assert "dry run" in r.output and "new" not in tr.read_text()
    monkeypatch.setattr(ui.questionary, "confirm", lambda *a, **k: pytest.fail("asked despite -y"))
    r = run(app, [*home.cli_args(), "rename", A, "new", "-y"])
    assert r.exit_code == 0, r.output
    assert '"customTitle":"new"' in tr.read_text()


def test_preamble_refuses_test_options_for_a_claude_session(home: Home, as_him, monkeypatch: pytest.MonkeyPatch):
    aged(home.transcript(A, home.folder("w")))
    monkeypatch.setattr(context_mod, "identify", lambda *a, **k: Caller("unscoped", B, "x", 1))
    r = run(app, [*home.cli_args(), "rename", A, "new", "-y"])
    assert r.exit_code == 1 and "honoured for the user only" in r.output
    # The config override in the environment is refused the same way, so a staffer cannot hand itself a scope.
    monkeypatch.setenv("CLAUDESTRA_CONFIG", str(home.config))
    r = run(app, ["rename", A, "new", "-y"])  # no test option given: the variable alone is refused
    assert r.exit_code == 1 and "honoured for the user only" in r.output


def test_preamble_refuses_a_machine_not_in_trust(home: Home):
    aged(home.transcript(A, home.folder("w")))
    r = run(app, [*home.cli_args(), "rename", A, "new", "-y"])
    assert r.exit_code == 1 and "does not match trust.yaml" in r.output


def test_names_print_as_written_and_lines_do_not_wrap(home: Home):
    home.transcript(A, home.folder("a-very-long-folder-name/that-goes/on-and-on/and-on-and-on"))
    home.staff_file(A, "[my-stack] manager", {"anyhost": "~/w"})
    r = run(app, [*home.cli_args(), "ls", "--all"])
    assert "[my-stack] manager" in r.output
    assert any("a-very-long-folder-name/that-goes/on-and-on/and-on-and-on" in line for line in r.output.splitlines())


def test_list_is_ls(home: Home):
    home.transcript(A, home.folder("w"))
    a = run(app, [*home.cli_args(), "ls", "--all", "--json"]).output
    assert a == run(app, [*home.cli_args(), "list", "--all", "--json"]).output and A in a


def test_completion_prints_and_installs_nothing():
    r = run(app, ["completion", "zsh"])
    assert r.exit_code == 0 and "compdef" in r.output
    assert run(app, ["--install-completion"]).exit_code != 0  # the installer is not offered
