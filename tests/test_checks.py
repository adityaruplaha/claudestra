"""The doctor: for each check, a fixture that breaks the fact it checks and the check reporting it; and an
action refused because a check it needs fails."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from claudestra import checks
from claudestra import claude_fs as claude_fs_mod
from claudestra.caller import Refused
from claudestra.claude_fs import KNOWN_VERSIONS, ClaudeFS
from claudestra.model import Machine
from claudestra.ops import guard
from claudestra.portable import slug
from claudestra.session import Session
from claudestra.trust import load

from conftest import HERE, HOST, HUMAN, A, B, C, Home

VERSION = KNOWN_VERSIONS[-1]


@pytest.fixture(autouse=True)
def no_managed_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Managed settings in the temporary folder, never the machine's /etc/claude-code."""
    monkeypatch.setattr(guard, "MANAGED", tmp_path / "etc")


def live(home: Home, pid: int, sid: str, cwd: Path, cmd: bytes = b"claude\0", **fields) -> dict:
    """A running session: its pid file, and its process in the fake /proc with the start time it records."""
    proc = home.home / "proc" / str(pid)
    proc.mkdir(parents=True)
    (proc / "stat").write_text(f"{pid} (claude) S 1 " + " ".join(["0"] * 17) + f" {1000 + pid} 0\n")
    (proc / "cmdline").write_bytes(cmd)
    rec = {
        "pid": pid,
        "sessionId": sid,
        "cwd": str(cwd),
        "procStart": str(1000 + pid),
        "kind": "interactive",
        "version": VERSION,
        **fields,
    }
    sessions = home.home / ".claude" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / f"{pid}.json").write_text(json.dumps(rec))
    return rec


def run_one(home: Home, name: str, deep: bool = True) -> checks.Result:
    fs, t, _ = home.setup()
    return checks.run(fs, [name], deep, t, Machine(HOST, "id-1", home.home))[0]


# --- the facts about Claude Code's files ------------------------------------------------------------


def test_pid_files_lacking_fields_or_malformed_fail(home: Home):
    w = home.folder("w")
    live(home, 10, A, w)
    assert run_one(home, "pid-files").status == checks.PASS
    sessions = home.home / ".claude" / "sessions"
    (sessions / "11.json").write_text(json.dumps({"pid": 11, "sessionId": B}))
    r = run_one(home, "pid-files")
    assert r.status == checks.FAIL and "11.json lacks cwd, procStart, kind" in r.detail
    (sessions / "11.json").write_text(
        json.dumps({"pid": 99, "sessionId": B, "cwd": "/", "procStart": "1", "kind": "interactive"})
    )
    r = run_one(home, "pid-files")
    assert r.status == checks.FAIL and "11.json: pid or sessionId malformed" in r.detail


def test_proc_start_that_disagrees_with_proc_fails(home: Home):
    w = home.folder("w")
    live(home, 10, A, w)
    live(home, 11, B, w, cmd=b"python\0")  # not claude: not checked
    assert run_one(home, "proc-start").status == checks.PASS
    pf = home.home / ".claude" / "sessions" / "10.json"
    pf.write_text(json.dumps({**json.loads(pf.read_text()), "procStart": "7"}))
    r = run_one(home, "proc-start")
    assert r.status == checks.FAIL and "10.json" in r.detail


def test_proc_start_with_no_running_claude_is_not_applicable(home: Home):
    live(home, 11, B, home.folder("w"), cmd=b"python\0")
    assert run_one(home, "proc-start").status == checks.NA


def test_a_running_session_filed_under_another_folder_fails_the_slug_rule(home: Home):
    w, elsewhere = home.folder("w"), home.folder("elsewhere")
    home.transcript(A, w)
    live(home, 10, A, w)
    live(home, 11, B, w)  # no transcript yet: not counted
    assert run_one(home, "slug-rule").status == checks.PASS
    (home.projects / slug(w) / f"{A}.jsonl").rename(home.transcript(A, elsewhere))
    r = run_one(home, "slug-rule")
    assert r.status == checks.FAIL and f"is filed under {slug(elsewhere)}" in r.detail


def test_slug_rule_with_no_running_transcript_is_not_applicable(home: Home):
    live(home, 11, B, home.folder("w"))
    assert run_one(home, "slug-rule").status == checks.NA


def test_transcript_ids_read_the_head_without_deep(home: Home):
    w = home.folder("w")
    home.transcript(A, w)
    assert run_one(home, "transcript-ids", deep=False).status == checks.PASS
    home.transcript(B, w, [{"type": "user", "sessionId": C}])
    r = run_one(home, "transcript-ids", deep=False)
    assert r.status == checks.FAIL and C in r.detail
    assert run_one(home, "record-types", deep=False).status == checks.PASS


def test_a_version_not_checked_against_warns(home: Home):
    w = home.folder("w")
    live(home, 10, A, w)
    assert run_one(home, "versions").status == checks.PASS
    live(home, 11, B, w, version="9.9.9")
    r = run_one(home, "versions")
    assert r.status == checks.WARN and "9.9.9" in r.detail


def test_versions_with_no_running_session_is_not_applicable(home: Home):
    assert run_one(home, "versions").status == checks.NA


def test_env_session_id_missing_or_different_warns(home: Home, monkeypatch: pytest.MonkeyPatch):
    w = home.folder("w")
    live(home, 10, A, w)
    shell = home.home / "proc" / "20"  # a shell under the session, which runs claudestra
    shell.mkdir(parents=True)
    (shell / "stat").write_text("20 (zsh) S 10 " + " ".join(["0"] * 17) + " 1020 0\n")
    monkeypatch.setattr(os, "getppid", lambda: 20)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    r = run_one(home, "env-session-id")
    assert r.status == checks.WARN and "not set" in r.detail
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", B)
    r = run_one(home, "env-session-id")
    assert r.status == checks.WARN and f"environment says {B}" in r.detail
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", A)
    assert run_one(home, "env-session-id").status == checks.PASS
    monkeypatch.setattr(os, "getppid", lambda: 30)  # a process gone from /proc
    assert run_one(home, "env-session-id").status == checks.NA


def test_bridge_ids_that_disagree_warn(home: Home):
    w = home.folder("w")
    tr = home.transcript(A, w)
    live(home, 10, A, w, bridgeSessionId="session_abc123")
    with tr.open("a") as fh:
        fh.write(json.dumps({"type": "bridge-session", "bridgeSessionId": "cse_abc123"}) + "\n")
    assert run_one(home, "bridge-ids").status == checks.PASS
    pf = home.home / ".claude" / "sessions" / "10.json"
    pf.write_text(json.dumps({**json.loads(pf.read_text()), "bridgeSessionId": "session_other"}))
    r = run_one(home, "bridge-ids")
    assert r.status == checks.WARN and "session_other vs cse_abc123" in r.detail


def test_bridge_ids_with_no_bridge_records_are_not_applicable(home: Home):
    w = home.folder("w")
    home.transcript(A, w)
    live(home, 10, A, w, bridgeSessionId="session_abc123")
    assert run_one(home, "bridge-ids").status == checks.NA


def test_a_subagent_that_is_not_a_sidechain_warns(home: Home):
    tr = home.transcript(A, home.folder("w"))
    sub = tr.parent / A / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.jsonl").write_text(json.dumps({"type": "assistant", "isSidechain": False, "sessionId": A}) + "\n")
    r = run_one(home, "subagents", deep=False)
    assert r.status == checks.WARN and "agent-1.jsonl" in r.detail
    assert run_one(home, "subagents").status == checks.WARN


def test_subagents_with_none_are_not_applicable(home: Home):
    home.transcript(A, home.folder("w"))
    assert run_one(home, "subagents").status == checks.NA


def test_a_job_not_named_by_its_session_fails(home: Home):
    jobs = home.home / ".claude" / "jobs"
    assert run_one(home, "jobs").status == checks.NA
    (jobs / A[:8]).mkdir(parents=True)
    (jobs / A[:8] / "state.json").write_text(json.dumps({"sessionId": A, "cwd": "/w"}))
    assert run_one(home, "jobs").status == checks.PASS
    (jobs / "deadbeef").mkdir()
    (jobs / "deadbeef" / "state.json").write_text(json.dumps({"sessionId": B, "cwd": "/w"}))
    r = run_one(home, "jobs")
    assert r.status == checks.FAIL and "deadbeef" in r.detail


def test_claude_agents_failing_or_lacking_fields_warns(home: Home, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(checks, "claude_agents", lambda: (None, "claude is not on PATH"))
    r = run_one(home, "claude-agents")
    assert r.status == checks.WARN and r.detail == "claude is not on PATH"
    monkeypatch.setattr(checks, "claude_agents", lambda: ([{"sessionId": A, "kind": "bg"}], ""))
    r = run_one(home, "claude-agents")
    assert r.status == checks.WARN and "lack cwd" in r.detail
    monkeypatch.setattr(checks, "claude_agents", lambda: ([{"sessionId": A, "kind": "bg", "cwd": "/"}], ""))
    assert run_one(home, "claude-agents").status == checks.PASS


def test_claude_agents_reports_why_it_could_not_run(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(claude_fs_mod.shutil, "which", lambda name: None)
    assert claude_fs_mod.claude_agents() == (None, "claude is not on PATH")


# --- the facts about this machine and its config -----------------------------------------------------


def test_a_machine_trust_does_not_describe_fails(home: Home):
    home.trust(f"machines:\n  {HOST}:\n    home: {home.home}\n    machine_id: id-1\n")
    assert run_one(home, "machine").status == checks.PASS
    home.trust(f"machines:\n  {HOST}:\n    home: {home.home}\n    machine_id: id-2\n")
    r = run_one(home, "machine")
    assert r.status == checks.FAIL and "not the id-2" in r.detail
    home.trust("machines: {}\n")
    assert "is not under machines" in run_one(home, "machine").detail


def test_settings_without_the_guard_fail(home: Home):
    r = run_one(home, "guard")
    assert r.status == checks.FAIL and "claudestra install guard" in r.detail
    fs, t, _ = home.setup()
    guard.install(fs, t.config, False)
    assert run_one(home, "guard").status == checks.PASS


def test_remote_control_off_or_unset_fails(home: Home):
    assert run_one(home, "remote-control").status == checks.PASS
    home.settings.write_text('{"remoteControlAtStartup": false}\n')
    r = run_one(home, "remote-control")
    assert r.status == checks.FAIL and "turns it off" in r.detail and "install remote-control" in r.detail
    home.settings.write_text("{}\n")
    r = run_one(home, "remote-control")
    assert r.status == checks.FAIL and "nothing turns it on" in r.detail


def test_remote_control_off_in_a_staffers_folder_fails(home: Home):
    w = home.folder("w")
    home.staff_file(A, "one", {HOST: "~/w"})
    (w / ".claude").mkdir()
    (w / ".claude" / "settings.local.json").write_text('{"remoteControlAtStartup": false}\n')
    r = run_one(home, "remote-control")
    # The user's settings turn it on, so installing it again would not help: no proposal.
    assert r.status == checks.FAIL and f"turns it off in {w}" in r.detail and "propose" not in r.detail


def test_remote_control_set_by_managed_settings(home: Home, tmp_path: Path):
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc" / "managed-settings.json").write_text('{"remoteControlAtStartup": false}\n')
    r = run_one(home, "remote-control")
    assert r.status == checks.FAIL and "managed settings" in r.detail


def test_a_full_run_returns_every_check_in_order(home: Home, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(checks, "claude_agents", lambda: (None, "stubbed"))
    fs, t, _ = home.setup()
    assert [r.name for r in checks.run(fs, None, False, t, Machine(HOST, "id-1", home.home))] == list(checks.CHECKS)


# --- a changing action refuses when a check it needs fails --------------------------------------------


def test_an_action_refuses_when_a_check_it_needs_fails(home: Home):
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    home.acting(HUMAN)
    sessions = home.home / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "11.json").write_text(json.dumps({"pid": 11, "sessionId": B}))  # pid-files fails
    with pytest.raises(Refused, match=r"claudestra doctor fails pid-files \(11.json lacks"):
        Session(A).stop().perform()
    (sessions / "11.json").unlink()
    assert str(Session(A).stop().perform()).startswith("not here")  # the checks pass, and the stop runs


def test_an_action_reads_the_config_it_was_given_for_its_checks(home: Home):
    """Start needs remote-control, which reads the staff files: those of the context's config, so a
    staffer's folder that turns it off refuses the start."""
    w = home.folder("w")
    home.transcript(A, w)
    home.staff_file(A, "one", {HERE: "~/w"})
    (w / ".claude").mkdir()
    (w / ".claude" / "settings.json").write_text('{"remoteControlAtStartup": false}\n')
    home.acting(HUMAN)
    with pytest.raises(Refused, match="claudestra doctor fails remote-control"):
        Session(A).start("/bin/false", "camtest-never").perform()


def test_a_check_given_no_config_reads_none(home: Home):
    """run() given no trust loads the default config folder, which conftest keeps empty."""
    fs = ClaudeFS(home.home, proc=home.home / "proc")
    r = checks.run(fs, ["machine"])[0]
    assert r.status == checks.FAIL and "not under machines" in r.detail
    assert load(HOST, home.home).staff == []
