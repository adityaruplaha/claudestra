"""The staff and lifecycle commands' own logic (cli/staff.py): which claude runs, autostart's arguments, the
staff list in its three forms, and hire, describe, dismiss and spawn from the command line; and the summary's
reading of who sent what (ops/summary.py)."""

from __future__ import annotations

import json
import uuid

import pytest
import typer

from claudestra.cli import app, staff, ui
from claudestra.ops import summary

from conftest import HERE, A, Answer, B, C, D, Home, aged, run

SOCKET = ["--socket", f"camtest-{uuid.uuid4().hex[:8]}"]  # never the real tmux server


def test_which_claude_runs(monkeypatch: pytest.MonkeyPatch):
    assert staff._claude("human", "/x/claude", None) == "/x/claude"
    assert staff._claude("login", "/x/claude", None) == "/x/claude"
    with pytest.raises(typer.Exit):  # --claude is not a session's to give
        staff._claude("folder", "/x/claude", None)
    monkeypatch.setenv("CAM_CLAUDE", "/test/claude")
    assert staff._claude("folder", None, "camtest-1") == "/test/claude"
    with pytest.raises(typer.Exit):  # the test stand-in only on a test tmux server
        staff._claude("folder", None, None)
    monkeypatch.delenv("CAM_CLAUDE")
    monkeypatch.setattr(staff.shutil, "which", lambda name: "/usr/bin/claude")
    assert staff._claude("folder", None, None) == "/usr/bin/claude"
    monkeypatch.setattr(staff.shutil, "which", lambda name: None)
    with pytest.raises(typer.Exit):
        staff._claude("human", None, None)


def test_autostart_with_nothing_to_start_or_with_names(home: Home, as_him):
    r = run(app, [*home.cli_args(), "autostart", "--claude", "/bin/false", "--dry-run", *SOCKET])
    assert r.exit_code == 1 and "autostarts nothing" in r.output
    with pytest.raises(typer.Exit):
        staff._sessions(None, ["one"], True)


def test_autostart_dry_run_plans_each_autostart_staffer(home: Home, as_him):
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    home.trust((home.config / "trust.yaml").read_text() + f"    autostart:\n      - {A}\n")
    r = run(app, [*home.cli_args(), "autostart", "--claude", "/bin/false", "--dry-run", *SOCKET])
    assert r.exit_code == 0, r.output
    assert "one" in r.output and "dry run; nothing changed" in r.output


@pytest.fixture
def staffed(home: Home, as_him):
    """A device scope over the home, a folder manager over ~/w, a specialist under it, and one elsewhere."""
    for sid, rel in ((A, "w"), (B, "w/sub"), (C, ""), (D, "x")):
        home.transcript(sid, home.folder(rel) if rel else home.home)
    home.staff_file(C, "device", {HERE: str(home.home)})
    home.staff_file(A, "manager", {HERE: "~/w"})
    home.staff_file(B, "worker", {HERE: "~/w/sub"})
    home.staff_file(D, "far", {"elsewhere": "~/x"})
    home.trust(
        (home.config / "trust.yaml").read_text() + f"sessions:\n  {A}:\n    scope: folder\n  {C}:\n    scope: device\n"
    )


def test_staff_list_as_a_table_a_tree_and_json(home: Home, staffed):
    r = run(app, [*home.cli_args(), "staff", "list"])
    assert r.exit_code == 0, r.output
    assert "(not on this machine)" in r.output and "folder" in r.output and "device" in r.output
    r = run(app, [*home.cli_args(), "staff", "list", "--tree"])
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    at = {name: next(i for i, ln in enumerate(lines) if f"{name} " in ln) for name in ("device", "manager", "worker")}
    assert lines[0].startswith("the user") and at["device"] < at["manager"] < at["worker"]
    indent = {n: len(lines[i]) - len(lines[i].lstrip("│├└─ ")) for n, i in at.items()}
    assert indent["device"] < indent["manager"] < indent["worker"]
    assert "far" not in r.output  # not on this machine
    r = run(app, [*home.cli_args(), "staff", "list", "--json"])
    rows = {row["name"]: row for row in json.loads(r.output)}
    assert rows["worker"]["answers_to"] == A and rows["manager"]["answers_to"] == C
    assert rows["device"]["answers_to"] is None and rows["far"]["folder"] is None and rows["far"]["answers_to"] is None


def test_hire_asks_for_the_description_at_a_terminal(home: Home, as_him, at_terminal, monkeypatch):
    aged(home.transcript(A, home.folder("w")))
    monkeypatch.setattr(ui.questionary, "text", lambda *a, **k: Answer("Works on w."))
    monkeypatch.setattr(ui.questionary, "confirm", lambda *a, **k: Answer(True))
    r = run(app, [*home.cli_args(), "staff", "hire", A, "--name", "one"])
    assert r.exit_code == 0, r.output
    assert "description: Works on w." in (home.config / "staff.d" / f"{A}.yaml").read_text()


def test_hire_refused_for_another_reason_says_so(home: Home, as_him):
    aged(home.transcript(A, home.folder("w")))
    home.staff_file(B, "taken", {HERE: "~/w"})
    r = run(app, [*home.cli_args(), "staff", "hire", A, "--name", "taken", "--description", "x", "-y"])
    assert r.exit_code == 1 and "already named 'taken'" in r.output


def test_describe_and_dismiss_from_the_command_line(home: Home, as_him):
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    r = run(app, [*home.cli_args(), "staff", "describe", "one", "Works on w now.", "-y"])
    assert r.exit_code == 0 and "described" in r.output
    assert "Works on w now." in (home.config / "staff.d" / f"{A}.yaml").read_text()
    r = run(app, [*home.cli_args(), "staff", "dismiss", "one", "--dry-run", *SOCKET])
    assert r.exit_code == 0 and (home.config / "staff.d" / f"{A}.yaml").exists()


def test_spawn_dry_run_plans_and_starts_nothing(home: Home, as_him, tmp_path):
    w = home.folder("w")
    args = ["session", "spawn", str(w), "--claude", "/bin/false", "--dry-run", *SOCKET]
    r = run(app, [*home.cli_args(), *args, "--staff", "--name", "new", "--prompt", "brief", "--description", "d"])
    assert r.exit_code == 0, r.output
    assert "dry run" in r.output and not any((home.config / "staff.d").iterdir())


# --- summary --------------------------------------------------------------------------------------------


def test_summary_counts_what_arrived_from_elsewhere(home: Home):
    from claudestra.claude_fs import ClaudeFS

    w = home.folder("w")
    user = lambda **kw: {"type": "user", "sessionId": A, **kw}  # noqa: E731
    t = home.transcript(
        A,
        w,
        [
            user(origin={"kind": "human"}, message={"content": "do it"}),
            user(isCompactSummary=True, message={"content": "summary"}),
            user(isMeta=True, message={"content": "meta"}),
            user(message={"content": [{"type": "tool_result", "content": "ok"}]}),
            user(origin={"kind": "peer"}, message={"content": "from a peer"}),
            user(message={}),
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "first"}]}},
            {
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "  done.  "}, {"type": "text", "text": " "}]},
            },
            {"type": "assistant", "message": {"content": "not a list"}},
        ],
    )
    s = summary.summarise(ClaudeFS(home.home), t)
    assert s.typed == ["do it"] and s.last_reply == "done."
    assert s.relayed["summary"] == 1 and s.relayed["meta"] == 1 and sum(s.relayed.values()) >= 3
    assert "tool_result" not in s.relayed
