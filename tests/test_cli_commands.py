"""The changing commands as the command line runs them: the plan, --dry-run, refusals turned into exits,
restricted mode on stderr, the preamble's refusals, and send and fetch."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from claudestra import context as context_mod
from claudestra import portable
from claudestra.caller import Caller, Refused
from claudestra.cli import app, ui
from claudestra.context import Context
from claudestra.ops import transfer
from claudestra.ops import trash as trash_ops
from claudestra.proctree import ClaudeProc, Proc
from claudestra.session import Session

from conftest import HERE, HUMAN, A, Answer, B, Home, aged, far_side, run

SOCKET = ["--socket", f"camtest-{uuid.uuid4().hex[:8]}"]  # never the real tmux server


@pytest.fixture
def as_unscoped(home: Home, monkeypatch: pytest.MonkeyPatch):
    """The caller taken to be a staffer with no scope, the fixture home and config not counted as an
    override (they are the test's world), and no Claude in the chain beyond it."""
    home.trust(f"machines:\n  {HERE}:\n    home: {home.home}\n    machine_id: {portable.machine_id()}\n")
    monkeypatch.setattr(context_mod, "identify", lambda *a, **k: Caller("unscoped", B, "x", 1))
    monkeypatch.setattr(context_mod, "claude_chain", lambda *a, **k: [])
    init = Context.__init__

    def unoverridden(self, *a, **k):
        init(self, *a, **k)
        self.overridden = False

    monkeypatch.setattr(Context, "__init__", unoverridden)


# --- each changing command: its plan, a dry run that changes nothing, and a real run where cheap ---------


def test_move_and_trash_and_restore_and_purge(home: Home, as_him, tmp_path: Path):
    w, x = home.folder("w"), home.folder("x")
    tr = aged(home.transcript(A, w))
    r = run(app, [*home.cli_args(), "session", "move", A, str(x), "--dry-run"])
    assert r.exit_code == 0 and "dry run" in r.output and tr.exists()
    r = run(app, [*home.cli_args(), "session", "move", A, str(x), "-y"])
    assert r.exit_code == 0 and "moved" in r.output and not tr.exists()
    r = run(app, [*home.cli_args(), "trash", "add", A, "--recent-minutes", "0", "--dry-run"])
    assert r.exit_code == 0 and f"trash {A}" in r.output and "dry run" in r.output
    r = run(app, [*home.cli_args(), "trash", "add", A, "--recent-minutes", "0", "-y"])
    assert r.exit_code == 0 and "trashed" in r.output
    [(entry, _)] = trash_ops.entries(home.setup()[0])
    r = run(app, [*home.cli_args(), "trash", "restore", entry.name, "--dry-run"])
    assert r.exit_code == 0 and "would restore" in r.output and trash_ops.entries(home.setup()[0])
    r = run(app, [*home.cli_args(), "trash", "restore", entry.name, "-y"])
    assert r.exit_code == 0 and "restored" in r.output and not trash_ops.entries(home.setup()[0])
    r = run(app, [*home.cli_args(), "trash", "purge", "--older-than", "1", "--dry-run"])
    assert r.exit_code == 0 and "nothing that old" in r.output


def test_start_stop_compact_and_type_plans(home: Home, as_him):
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    claude = ["--claude", "/bin/sh"]
    r = run(app, [*home.cli_args(), "session", "start", "one", *claude, "--dry-run", *SOCKET])
    assert r.exit_code == 0 and "would start  one" in r.output
    r = run(app, [*home.cli_args(), "session", "stop", "one", "--dry-run", *SOCKET])
    assert r.exit_code == 0 and "not here  one" in r.output
    r = run(app, [*home.cli_args(), "session", "compact", A, *claude, "--dry-run", *SOCKET])
    assert r.exit_code == 0 and f"compact {A}" in r.output and "dry run" in r.output
    r = run(app, [*home.cli_args(), "session", "type", "one", "hello", "--dry-run", *SOCKET])
    assert r.exit_code == 1 and "not running in claudestra's tmux" in r.output


def test_trust_and_audit_fix_and_the_login_unit_dry_runs(home: Home, as_him):
    tr = home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    with tr.open("a") as fh:
        fh.write(json.dumps({"type": "custom-title", "customTitle": "one renamed", "sessionId": A}) + "\n")
    before = (home.config / "trust.yaml").read_text()
    r = run(app, [*home.cli_args(), "trust", "grant", A, "folder", "--dry-run"])
    assert r.exit_code == 0 and "gets folder scope" in r.output and (home.config / "trust.yaml").read_text() == before
    r = run(app, [*home.cli_args(), "audit", "names", "--fix", "--dry-run"])
    assert "'one' -> 'one renamed'" in r.output and "dry run" in r.output
    r = run(app, [*home.cli_args(), "audit", "names", "--fix", "-y"])
    assert r.exit_code == 0 and "fixed 1" in r.output
    r = run(app, [*home.cli_args(), "install", "login-unit", "--dry-run"])
    assert r.exit_code == 0 and "would write" in r.output


# --- refusals, turned into an exit with the reason ------------------------------------------------------


def test_an_unscoped_session_is_refused(home: Home, as_unscoped):
    aged(home.transcript(A, home.folder("w")))
    home.staff_file(A, "one", {HERE: "~/w"})
    for args in (
        ["session", "move", A, str(home.folder("x")), "-y"],
        ["trash", "add", A, "--recent-minutes", "0", "-y"],
        ["trash", "purge", "--older-than", "1", "-y"],
        ["trust", "grant", A, "folder", "-y"],
        ["session", "attach"],
        ["session", "stop", "one", "-y", *SOCKET],
    ):
        r = run(app, [*home.cli_args(), *args])
        assert r.exit_code == 1 and "refused" in r.output, (args, r.output)
    assert Session(A).here if Context._current else True


def test_preamble_refuses_a_config_with_errors_and_a_failing_doctor_check(home: Home, as_him):
    aged(home.transcript(A, home.folder("w")))
    (home.config / "staff.d" / "not-a-session-id.yaml").write_text('name: "x"\nfolder: {}\ndescription: d\n')
    r = run(app, [*home.cli_args(), "session", "rename", A, "new", "-y"])
    assert r.exit_code == 1 and "the config has errors" in r.output
    (home.config / "staff.d" / "not-a-session-id.yaml").unlink()
    tr = home.transcript(B, home.folder("w"))
    with tr.open("a") as fh:  # a record type claudestra does not know only warns
        fh.write(json.dumps({"type": "something-new", "sessionId": B}) + "\n")
    r = run(app, [*home.cli_args(), "session", "rename", A, "new", "-y", "--dry-run"])
    assert r.exit_code == 0
    with tr.open("a") as fh:  # another session's ID in B's transcript, which identity rests on
        fh.write(json.dumps({"type": "user", "sessionId": A}) + "\n")
    r = run(app, [*home.cli_args(), "session", "rename", A, "new", "-y"])
    assert r.exit_code == 1 and "doctor fails" in r.output and "transcript-ids" in r.output


# --- restricted mode, as the command line shows it ----------------------------------------------------


def test_restricted_mode_is_announced_first_on_stderr(home: Home, monkeypatch: pytest.MonkeyPatch):
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "mgr", {HERE: "~/w"})
    sessions = home.home / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "30.json").write_text(json.dumps({"pid": 30, "sessionId": A, "procStart": "1030", "name": "mgr"}))
    claude = ClaudeProc(Proc(30, 1, "1030", "claude", "/usr/bin/claude"), None, 2)
    monkeypatch.setattr(context_mod, "claude_chain", lambda *a, **k: [claude])
    r = run(app, [*home.cli_args(), "ls", "--all", "--json"])
    assert r.exit_code == 0
    assert r.stderr.splitlines()[0].startswith("restricted mode: a Claude process is in the chain")
    assert r.stderr.splitlines()[1].startswith("caller: a Claude process (pid 30)")
    assert json.loads(r.stdout)[0]["session"] == A  # the --json output on stdout stays clean


def test_no_banner_without_claude(home: Home, as_him):
    home.transcript(A, home.folder("w"))
    r = run(app, [*home.cli_args(), "ls", "--all"])
    assert "restricted mode" not in r.output


# --- send and fetch -----------------------------------------------------------------------------------


def test_send_and_fetch_as_actions(home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lt, _, far_home = far_side(tmp_path)
    (far_home / "dest").mkdir()
    aged(
        home.transcript(
            A, home.folder("work"), [{"type": "user", "uuid": "u", "sessionId": A, "cwd": str(home.home / "work")}]
        )
    )
    home.staff_file(A, "a", {HERE: "~/work"})
    monkeypatch.setattr(transfer, "SSHTransport", lambda conf: lt)
    c = home.acting(HUMAN)
    f = home.config / "trust.yaml"
    f.write_text(f.read_text() + "    ssh: stand-in\n")  # the far side accepts connections
    c.refresh()
    with pytest.raises(Refused, match="not under machines"):
        Session(A).send("nowhere").perform()
    c._subject = Caller("device", B, "d", 1)
    with pytest.raises(Refused, match="needs one of: user"):
        Session(A).send(HERE, str(far_home / "dest")).perform()
    c._subject = HUMAN
    plan = Session(A).send(HERE, str(far_home / "dest")).perform()
    assert plan is not None and not Session(A).here
    assert list((far_home / ".claude" / "projects").glob(f"*/{A}.jsonl"))
    c._subject = Caller("device", B, "d", 1)
    with pytest.raises(Refused, match="fetch is for the user"):
        c.fetch(A, HERE, str(far_home / "dest"), home.folder("work")).perform()
    c._subject = HUMAN
    c.fetch(A, HERE, str(far_home / "dest"), home.folder("work")).perform()
    assert Session(A).here


def test_send_on_the_command_line_needs_the_full_id_typed(
    home: Home, as_him, at_terminal, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    lt, _, far_home = far_side(tmp_path)
    (far_home / "dest").mkdir()
    tr = aged(home.transcript(A, home.folder("work")))
    monkeypatch.setattr(transfer, "SSHTransport", lambda conf: lt)
    (home.config / "trust.yaml").write_text((home.config / "trust.yaml").read_text() + "    ssh: stand-in\n")
    monkeypatch.setattr(ui.questionary, "text", lambda *a, **k: Answer(A[:8]))  # not the full ID
    r = run(app, [*home.cli_args(), "machine", "send", A, HERE, "--to", str(far_home / "dest")])
    assert r.exit_code == 1 and "did not confirm" in r.output and tr.exists()
    r = run(app, [*home.cli_args(), "machine", "send", A, HERE, "--to", str(far_home / "dest"), "--dry-run"])
    assert r.exit_code == 0 and tr.exists()


def test_every_reading_command_prints(home: Home, as_him):
    tr = home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    for args, expect in (
        (["show", A], "one"),
        (["summary", A], "typed prompts"),
        (["whoami"], "the user, at a terminal"),
        (["check"], ""),
        (["doctor", "slug-rule"], "slug-rule"),
        (["audit", "names"], "names"),
        (["permissions"], "start"),
        (["trust", "show"], "machines:"),
        (["ls"], "one"),
    ):
        r = run(app, [*home.cli_args(), *args])
        assert r.exit_code in (0, 1) and expect in r.output, (args, r.output)
    assert tr.exists()


def test_hire_and_dismiss_on_the_command_line(home: Home, as_him):
    home.transcript(A, home.folder("w"))
    r = run(app, [*home.cli_args(), "staff", "hire", A, "--description", "Works on w.", "--dry-run"])
    assert r.exit_code == 0 and f"hire {A}" in r.output and not (home.config / "staff.d" / f"{A}.yaml").exists()
    r = run(app, [*home.cli_args(), "staff", "hire", A, "--name", "one", "--description", "Works on w.", "-y"])
    assert r.exit_code == 0 and "hired" in r.output
    r = run(app, [*home.cli_args(), "staff", "dismiss", "one", "-y", *SOCKET])
    assert r.exit_code == 0 and (home.config / "staff-dismissed.d" / f"{A}.yaml").exists()


def test_the_login_unit_runs_autostart_and_nothing_else(home: Home, capsys):
    import typer

    from claudestra.cli.base import Ctx
    from claudestra.cli.staff import _lifecycle
    from claudestra.ops import unit

    assert "ExecStart=/x/claudestra autostart --claude /x/claude" in unit.unit_text(["/x/claudestra"], "/x/claude")
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    home.acting(Caller("login"))
    with pytest.raises(typer.Exit):  # `session start one`, as the login unit
        _lifecycle(Ctx(), ["one"], True, False, SOCKET[1], False, True, True)
    assert "only runs `claudestra autostart`" in capsys.readouterr().err


def test_every_reading_command_prints_json(home: Home, as_him):
    aged(home.transcript(A, home.folder("w")))
    home.staff_file(A, "one", {HERE: "~/w"})
    for args in (
        ["ls"], ["show", A], ["summary", A], ["whoami"], ["check"], ["audit"], ["doctor", "versions"],
        ["permissions"], ["preferences"], ["log"], ["staff", "list"], ["trash", "list"], ["machine", "list"],
    ):  # fmt: skip
        r = run(app, [*home.cli_args(), *args, "--json"])
        json.loads(r.stdout), args
