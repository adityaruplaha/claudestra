"""The context, sessions and the reading actions (DESIGN.md §4, §5)."""

from __future__ import annotations

import json
import socket

import pytest

from claudestra.actions.audit import Audit
from claudestra.actions.ls import List
from claudestra.actions.whoami import Whoami
from claudestra.caller import Refused
from claudestra.context import Context
from claudestra.session import Session

from conftest import A, B, C, Home

HERE = socket.gethostname()  # a context reads this machine's hostname


def test_the_context_is_one_per_process(home: Home):
    first = Context(home.home, home.config)
    assert Context.current() is first
    with pytest.raises(RuntimeError, match="one per process"):
        Context(home.home, home.config)
    with Context.use(home.home, home.config) as inner:  # a test's own, the previous put back after
        assert Context.current() is inner is not first
    assert Context.current() is first


def test_a_session_reads_through_the_context(home: Home):
    home.transcript(A, home.folder("top"))
    home.transcript(B, home.folder("top/sub"))
    home.staff_file(A, "mgr", {HERE: "~/top"})
    home.staff_file(B, "inner", {HERE: "~/top/sub"})
    home.staff_file(C, "far", {"elsewhere": "~/x"})
    home.trust(f"sessions:\n  {A}:\n    scope: folder\n")
    c = Context(home.home, home.config)
    inner, mgr, far = c.staffer("inner"), c.staffer(A[:8]), c.staffer("far")
    assert type(c.session("inner")) is Session and c.session("inner") == inner  # a session, whoever asks
    assert (
        inner == c.session(B[:8]) and inner.here and inner.state == "stopped" and inner.folder == home.folder("top/sub")
    )
    assert inner.managers == [mgr] and inner.managed_by == "mgr" and mgr.scope == "folder"
    assert not far.here and far.staff_name == "far" and far.state == "not on this machine"
    assert c.session("far").on_staff and sorted(x.id for x in c.staff()) == [A, B, C]
    with pytest.raises(Refused, match="no session matches"):
        c.session("nothing-like-it")
    assert inner.running_pid is None and far.stores is None
    assert {label.split("/")[-1] for label, _ in inner.stores.items} == {f"{B}.jsonl"}
    (home.config / "staff.d" / f"{B}.yaml").unlink()  # dismissed by hand: what it read is refused from now on
    c.refresh()
    assert not inner.on_staff
    with pytest.raises(Refused, match="no longer on the staff"):
        _ = inner.staff_name
    with pytest.raises(Refused, match="not on the staff"):
        c.staffer(B)


def test_restricted_under_claude_with_every_claude_in_the_chain(home: Home):
    """Two Claude processes in the chain: both are reported, nearest first, and the nearest is the subject."""
    home.fake_proc(
        [
            (40, 30, "zsh", "/usr/bin/zsh"),
            (30, 20, "claude", "/opt/claude-code/bin/claude"),
            (20, 10, "zsh", "/usr/bin/zsh"),
            (10, 1, "claude", "/usr/bin/claude"),
        ]
    )
    sess = home.home / ".claude" / "sessions"
    sess.mkdir(parents=True)
    for pid, sid, name in ((30, A, "inner"), (10, B, "outer")):
        (sess / f"{pid}.json").write_text(
            json.dumps(
                {"pid": pid, "sessionId": sid, "procStart": str(1000 + pid), "kind": "interactive", "name": name}
            )
        )
    c = Context(home.home, home.config, proc=home.home / "proc", start_pid=40)
    assert c.restricted
    assert c.chain_sessions() == [A, B]
    assert [(p.depth, p.proc.pid, p.session_name) for p in c.chain] == [(2, 30, "inner"), (4, 10, "outer")]
    assert c.chain[0].describe().startswith("depth 2: pid 30, /opt/claude-code/bin/claude, session " + A)


def test_not_restricted_without_claude(home: Home):
    home.fake_proc([(40, 1, "bash", "/usr/bin/bash")])
    c = Context(home.home, home.config, proc=home.home / "proc", start_pid=40)
    assert not c.restricted and c.chain == [] and c.chain_sessions() == []


def test_reading_actions(home: Home):
    home.transcript(A, home.folder("w"))
    home.transcript(B, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    home.staff_file(C, "far", {HERE: "~/x"})
    Context(home.home, home.config)
    listing = List().perform()
    assert [s.id for s in listing.sessions] == [A] and [a.name for a in listing.elsewhere] == ["far"]
    assert listing.total == 2 and listing.running == 0
    assert {s.id for s in List(show_all=True).perform().sessions} == {A, B}
    with pytest.raises(Refused, match="no such report"):
        Audit(["nonsense"]).perform()
    assert set(Audit(["orphans"]).perform()) == {"orphans"}
    assert Session(A).show().perform()["staffer"] == "one"
    assert Session(A).summary().perform().typed == ["hello"]


def test_whoami_reports_restriction_and_reach(home: Home):
    home.fake_proc([(40, 30, "zsh", "/usr/bin/zsh"), (30, 1, "claude", "/opt/claude-code/bin/claude")])
    sess = home.home / ".claude" / "sessions"
    sess.mkdir(parents=True)
    (sess / "30.json").write_text(
        json.dumps({"pid": 30, "sessionId": A, "procStart": "1030", "kind": "interactive", "name": "mgr"})
    )
    home.transcript(A, home.folder("top"))
    home.transcript(B, home.folder("top/sub"))
    home.staff_file(A, "mgr", {HERE: "~/top"})
    home.staff_file(B, "inner", {HERE: "~/top/sub"})
    home.trust(f"sessions:\n  {A}:\n    scope: folder\n")
    Context(home.home, home.config, proc=home.home / "proc", start_pid=40)
    me = Whoami().perform()
    assert me.restricted and me.subject.kind == "folder" and me.subject.session == A
    assert [p.session_id for p in me.chain] == [A]
    assert me.managed_by == "the user (no device-scope manager on this machine)"


@pytest.mark.parametrize(
    "scope, folders, expected",
    [
        ("folder", {HERE: "~/top"}, "(mgr), folder scope over ~/top"),
        ("device", {HERE: "~/top"}, "(mgr), device scope on this machine"),
        ("device", {"other-host": "~/top"}, "(mgr), device scope on other-host"),
        (None, {HERE: "~/top"}, "(mgr), a specialist (no scope), on this machine"),
        ("unregistered", {}, "(from-pid-file), not on the staff, so no scope"),
    ],
)
def test_caller_line_names_the_staffer_and_its_reach(home: Home, scope, folders, expected):
    home.fake_proc([(40, 30, "zsh", "/usr/bin/zsh"), (30, 1, "claude", "/opt/claude-code/bin/claude")])
    sess = home.home / ".claude" / "sessions"
    sess.mkdir(parents=True)
    (sess / "30.json").write_text(
        json.dumps({"pid": 30, "sessionId": A, "procStart": "1030", "kind": "interactive", "name": "from-pid-file"})
    )
    home.transcript(A, home.folder("top"))
    if scope != "unregistered":
        home.staff_file(A, "mgr", folders)
    if scope in ("folder", "device"):
        home.trust(f"sessions:\n  {A}:\n    scope: {scope}\n")
    c = Context(home.home, home.config, proc=home.home / "proc", start_pid=40)
    assert c.restricted
    assert c.caller_line() == f"caller: session {A} {expected}"


def test_caller_line_without_a_session_file(home: Home):
    home.fake_proc([(40, 30, "zsh", "/usr/bin/zsh"), (30, 1, "claude", "/opt/claude-code/bin/claude")])
    c = Context(home.home, home.config, proc=home.home / "proc", start_pid=40)
    assert c.caller_line() == "caller: a Claude process (pid 30) with no session file, so no session can be named"
