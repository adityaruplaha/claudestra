"""The operations that change things, against fixture homes, a fake /proc, and a second fixture home
standing in for the other machine; including what happens when they fail part way."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from claudestra import caller as caller_mod
from claudestra import portable
from claudestra.caller import Refused, identify
from claudestra.ops import move as move_ops
from claudestra.ops import rewrite, transfer
from claudestra.ops import trash as trash_ops
from claudestra.portable import slug

from conftest import HOST, HUMAN, A, B, Home, aged, far_side

# --- the process chain and the login caller ---------------------------------------------------------


def test_identify_from_the_process_chain(home: Home):
    home.fake_proc(
        [
            (30, 20, "zsh", "/usr/bin/zsh"),
            (20, 10, "claude", "/opt/claude-code/bin/claude"),
            (10, 1, "zsh", "/usr/bin/zsh"),
        ]
    )
    sess = home.home / ".claude" / "sessions"
    sess.mkdir(parents=True)
    (sess / "20.json").write_text(
        json.dumps({"pid": 20, "sessionId": A, "procStart": "1020", "cwd": "/x", "kind": "interactive", "name": "mgr"})
    )
    home.trust(f"sessions:\n  {A}:\n    scope: device\n")
    home.staff_file(A, "mgr", {HOST: "~/x"})
    fs, t, _ = home.setup()
    c = identify(fs, HOST, t, start_pid=30, claude_env=False, tty=False)
    assert (c.kind, c.session, c.pid) == ("device", A, 20)
    (home.config / "staff.d" / f"{A}.yaml").rename(home.config / "staff.d" / "x")  # dismissed: its scope waits
    (home.config / "staff-dismissed.d").mkdir()
    (home.config / "staff.d" / "x").rename(home.config / "staff-dismissed.d" / f"{A}.yaml")
    fs, t, _ = home.setup()
    assert not t.errors and identify(fs, HOST, t, start_pid=30, claude_env=False, tty=False).kind == "unscoped"
    (home.config / "staff-dismissed.d" / f"{A}.yaml").unlink()  # neither on the staff nor dismissed: an error
    fs, t, _ = home.setup()
    assert any("no staff file; hire it, or revoke the scope" in e for e in t.errors)
    (sess / "20.json").unlink()  # a Claude process with no session file is refused, not guessed at
    with pytest.raises(Refused, match="no session file"):
        identify(fs, HOST, t, start_pid=30, claude_env=False, tty=True)


def test_no_claude_and_no_terminal_is_refused(home: Home):
    home.fake_proc([(30, 1, "bash", "/usr/bin/bash")])
    fs, t, _ = home.setup()
    with pytest.raises(Refused, match="terminal"):
        identify(fs, HOST, t, start_pid=30, claude_env=False, tty=False)
    with pytest.raises(Refused, match="environment"):
        identify(fs, HOST, t, start_pid=30, claude_env=True, tty=True)
    assert identify(fs, HOST, t, start_pid=30, claude_env=False, tty=True).kind == "human"


def test_login_caller_needs_the_units_invocation_and_cgroup(home: Home, monkeypatch: pytest.MonkeyPatch):
    home.fake_proc([(30, 1, "systemd", "/usr/lib/systemd/systemd")])
    (home.home / "proc" / "self").mkdir()
    cgroup = home.home / "proc" / "self" / "cgroup"
    monkeypatch.setattr(caller_mod, "login_invocation", lambda: "inv-1")
    monkeypatch.setenv("INVOCATION_ID", "inv-1")
    fs, t, _ = home.setup()
    cgroup.write_text("0::/user.slice/user-1000.slice/user@1000.service/app.slice/run-u7.service\n")
    with pytest.raises(Refused, match="terminal"):  # systemd-run with the unit's ID: another cgroup
        identify(fs, HOST, t, start_pid=30, claude_env=False, tty=False)
    cgroup.write_text("0::/user.slice/user-1000.slice/user@1000.service/app.slice/claudestra-autostart.service\n")
    assert identify(fs, HOST, t, start_pid=30, claude_env=False, tty=False).kind == "login"


def test_move_carries_every_store_and_rewrites_cwd(home: Home):
    src, dst = home.folder("old"), home.folder("new")
    (src / "sub").mkdir()
    (dst / "sub").mkdir()
    tr = home.transcript(
        A,
        src,
        [
            {"type": "user", "uuid": "u1", "sessionId": A, "cwd": str(src), "message": {"content": f"look at {src}"}},
            {"type": "user", "uuid": "u2", "sessionId": A, "cwd": str(src / "sub")},
        ],
    )
    with tr.open("ab") as fh:  # a cut tool output: invalid UTF-8 and a lone surrogate escape
        fh.write(b'{"type":"user","cwd":"' + str(src).encode() + b'","x":"\\ud83d"}\n\xff\xfe not json\n')
    sdir = tr.parent / A / "subagents"
    sdir.mkdir(parents=True)
    (sdir / "staffer-a1.jsonl").write_text(json.dumps({"isSidechain": True, "sessionId": A, "cwd": str(src)}) + "\n")
    other = home.projects / slug(home.folder("elsewhere")) / A / "tool-results"
    other.mkdir(parents=True)
    (other / "t1.txt").write_text("x")
    home.staff_file(A, "staffer-a", {HOST: "~/old", "otherhost": "~/far"})
    fs, t, m = home.setup()
    plan = move_ops.plan(fs, HOST, t, m.sessions[A], dst, None)
    assert plan.cwd_changes == {str(src): 3, str(src / "sub"): 1}
    move_ops.apply(fs, HOST, HUMAN, plan)

    new = home.projects / slug(dst)
    assert not tr.exists() and (new / f"{A}.jsonl").exists()
    raw = (new / f"{A}.jsonl").read_bytes()
    assert b"\xff\xfe not json" in raw  # kept byte for byte
    recs = [json.loads(x) for x in raw.split(b"\n")[:3]]
    assert [r["cwd"] for r in recs] == [str(dst), str(dst / "sub"), str(dst)]
    assert str(src) in recs[0]["message"]["content"]  # what was said keeps its paths
    assert json.loads((new / A / "subagents" / "staffer-a1.jsonl").read_text())["cwd"] == str(dst)
    assert (new / A / "tool-results" / "t1.txt").exists() and not other.parent.exists()
    drop = (home.config / "staff.d" / f"{A}.yaml").read_text()
    assert f"{HOST}: ~/new" in drop and "otherhost: ~/far" in drop


def test_move_failing_part_way_puts_everything_back(home: Home, monkeypatch: pytest.MonkeyPatch):
    src, dst = home.folder("old"), home.folder("new")
    tr = home.transcript(A, src)
    (tr.parent / A).mkdir()
    (tr.parent / A / "custom-title.json").write_text("{}")
    before = tr.read_bytes()
    fs, t, m = home.setup()
    plan = move_ops.plan(fs, HOST, t, m.sessions[A], dst, None)
    real = portable.move_into
    calls = []

    def flaky(a, b):
        calls.append(a)
        if len(calls) == 2:
            raise OSError("disk full")
        real(a, b)

    monkeypatch.setattr(portable, "move_into", flaky)
    with pytest.raises(Refused, match="put back"):
        move_ops.apply(fs, HOST, HUMAN, plan)
    monkeypatch.setattr(portable, "move_into", real)
    assert tr.read_bytes() == before and (tr.parent / A / "custom-title.json").exists()
    assert not (home.projects / slug(dst) / f"{A}.jsonl").exists()


def test_move_refusals(home: Home):
    lab, out = home.folder("lab/proj"), home.folder("out")
    home.transcript(A, lab)
    home.staff_file(A, "a", {HOST: "~/lab/proj"})
    home.trust(f"machines:\n  {HOST}:\n    home: /h\n    machine_id: x\n    protected:\n      - ~/lab\n")
    fs, t, m = home.setup()
    with pytest.raises(Refused, match="protected"):
        move_ops.plan(fs, HOST, t, m.sessions[A], out, None)
    move_ops.plan(fs, HOST, t, m.sessions[A], home.folder("lab/other"), None)  # inside: fine


def test_rewrite_survives_bad_encodings(tmp_path: Path):
    f = tmp_path / "t.jsonl"
    f.write_bytes(b'{"cwd":"/a","t":"\\ud83d"}\n\xff\n{"cwd":"/b"}')
    assert rewrite.rewrite_file(f, rewrite.mapper([("/a", "/z")]), None) == {"/a": 1}
    assert f.read_bytes().split(b"\n")[1:] == [b"\xff", b'{"cwd":"/b"}']


# --- trash ----------------------------------------------------------------------------------------


def test_trash_restore_purge(home: Home):
    tr = aged(home.transcript(B, home.folder("w")))
    (fh := home.home / ".claude" / "file-history" / B).mkdir(parents=True)
    (fh / "f@v1").write_text("x")
    fs, t, m = home.setup()
    trash_ops.apply(fs, HUMAN, trash_ops.plan(fs, t, m.sessions[B], recent_minutes=10))
    assert not tr.exists() and not fh.exists()
    trash_ops.restore(fs, HUMAN, B[:8], dry=False)
    assert tr.exists() and (fh / "f@v1").exists() and trash_ops.entries(fs) == []

    aged(tr)
    fs, t, m = home.setup()
    entry = trash_ops.apply(fs, HUMAN, trash_ops.plan(fs, t, m.sessions[B], 10))
    os.utime(entry, (0, 0))
    doomed = trash_ops.purgeable(fs, 1)
    assert doomed == [entry]
    trash_ops.purge(fs, HUMAN, doomed)
    assert not entry.exists()


def test_trash_failing_part_way_then_restore(home: Home, monkeypatch: pytest.MonkeyPatch):
    tr = aged(home.transcript(B, home.folder("w")))
    (fh := home.home / ".claude" / "file-history" / B).mkdir(parents=True)
    fs, t, m = home.setup()
    plan = trash_ops.plan(fs, t, m.sessions[B], 10)
    real = portable.move_into
    calls = []

    def flaky(a, b):
        calls.append(a)
        if len(calls) == 2:
            raise OSError("disk full")
        real(a, b)

    monkeypatch.setattr(portable, "move_into", flaky)
    with pytest.raises(OSError):
        trash_ops.apply(fs, HUMAN, plan)
    monkeypatch.setattr(portable, "move_into", real)
    assert not tr.exists() and fh.exists()  # the first move happened, the manifest records it
    trash_ops.restore(fs, HUMAN, B[:8], dry=False)
    assert tr.exists() and fh.exists()


def test_trash_refusals(home: Home):
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "a", {HOST: "~/w"})
    fs, t, m = home.setup()
    with pytest.raises(Refused, match="written"):
        trash_ops.plan(fs, t, m.sessions[A], 10)


def test_symlinked_files_are_never_split(home: Home):
    w = home.folder("w")
    ta, tb = aged(home.transcript(A, w)), aged(home.transcript(B, w))
    (real := ta.parent / A / "subagents").mkdir(parents=True)
    (real / "staffer-x.jsonl").write_text("{}\n")
    (linked := tb.parent / B / "subagents").mkdir(parents=True)
    (linked / "staffer-x.jsonl").symlink_to(real / "staffer-x.jsonl")
    fs, t, m = home.setup()
    with pytest.raises(Refused, match="target of the symlink"):
        trash_ops.plan(fs, t, m.sessions[A], 0)
    with pytest.raises(Refused, match="is a symlink"):
        trash_ops.plan(fs, t, m.sessions[B], 0)


# --- send and fetch -----------------------------------------------------------------------------------


def test_send_then_fetch_round_trip(home: Home, tmp_path: Path):
    lt, machines, far_home = far_side(tmp_path)
    (far_home / "dest").mkdir()
    tr = aged(
        home.transcript(
            A, home.folder("work"), [{"type": "user", "uuid": "u", "sessionId": A, "cwd": str(home.home / "work")}]
        )
    )
    home.staff_file(A, "a", {HOST: "~/work", lt.hostname: "~/dest"})
    fs, t, m = home.setup()
    with pytest.raises(Refused, match="confirm"):
        transfer.send(fs, HOST, machines, t, HUMAN, m.sessions[A], lt, None, None, False, lambda sid: False)
    assert tr.exists()

    plan = transfer.send(fs, HOST, machines, t, HUMAN, m.sessions[A], lt, None, None, False, lambda sid: sid == A)
    landed = far_home / ".claude" / "projects" / slug(far_home / "dest") / f"{A}.jsonl"
    assert plan.cwd_changes and landed.exists() and not tr.exists()
    assert json.loads(landed.read_text())["cwd"] == str(far_home / "dest")
    assert len(trash_ops.entries(fs)) == 1

    fs, t, _ = home.setup()
    transfer.fetch(fs, HOST, machines, t, HUMAN, A, lt, None, home.home / "work", t.staff[0].folders, False)
    assert json.loads(tr.read_text())["cwd"] == str(home.home / "work") and not landed.exists()


def test_send_and_fetch_copy_memory_only_when_asked_adding_what_is_missing(home: Home, tmp_path: Path):
    lt, machines, far_home = far_side(tmp_path)
    (far_home / "dest").mkdir()
    work = home.folder("work")
    aged(home.transcript(A, work, [{"type": "user", "uuid": "u", "sessionId": A, "cwd": str(work)}]))
    home.staff_file(A, "a", {HOST: "~/work", lt.hostname: "~/dest"})
    here_mem = home.projects / slug(work) / "memory"
    here_mem.mkdir(parents=True)
    (here_mem / "MEMORY.md").write_text("index\n")
    there_mem = far_home / ".claude" / "projects" / slug(far_home / "dest") / "memory"
    there_mem.mkdir(parents=True)
    (there_mem / "MEMORY.md").write_text("theirs\n")
    fs, t, m = home.setup()
    with pytest.raises(Refused, match="differs at the destination"):
        transfer.send(fs, HOST, machines, t, HUMAN, m.sessions[A], lt, None, None, False, lambda sid: True, True)
    (there_mem / "MEMORY.md").unlink()
    plan = transfer.send(fs, HOST, machines, t, HUMAN, m.sessions[A], lt, None, None, False, lambda sid: True, True)
    assert plan.memory and (there_mem / "MEMORY.md").read_text() == "index\n" and (here_mem / "MEMORY.md").exists()
    (there_mem / "notes.md").write_text("from there\n")
    fs, t, _ = home.setup()
    transfer.fetch(fs, HOST, machines, t, HUMAN, A, lt, None, work, t.staff[0].folders, False, True)
    assert (here_mem / "notes.md").read_text() == "from there\n"


def test_send_failing_at_the_push_takes_back_what_arrived(home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lt, machines, far_home = far_side(tmp_path)
    (far_home / "dest").mkdir()
    tr = aged(home.transcript(A, home.folder("work")))
    fs, t, m = home.setup()
    real = lt.push

    def half_push(staging, rels):
        real(staging, rels)
        raise Refused("connection dropped")

    monkeypatch.setattr(lt, "push", half_push)
    with pytest.raises(Refused, match="copy there was moved to its trash"):
        transfer.send(
            fs, HOST, machines, t, HUMAN, m.sessions[A], lt, str(far_home / "dest"), None, False, lambda sid: True
        )
    assert tr.exists() and not list((far_home / ".claude" / "projects").glob(f"*/{A}.jsonl"))


def test_fetch_failing_at_the_far_trash_leaves_nothing_here(
    home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    lt, machines, far_home = far_side(tmp_path)
    (far_home / "src").mkdir()
    far_tr = far_home / ".claude" / "projects" / slug(far_home / "src") / f"{A}.jsonl"
    far_tr.parent.mkdir(parents=True)
    far_tr.write_text(json.dumps({"type": "user", "sessionId": A, "cwd": str(far_home / "src")}) + "\n")
    fs, t, _ = home.setup()
    real = lt.helper
    monkeypatch.setattr(
        lt,
        "helper",
        lambda req: (_ for _ in ()).throw(Refused("ssh dropped")) if req["action"] == "trash" else real(req),
    )
    with pytest.raises(Refused, match="nothing changed"):
        transfer.fetch(fs, HOST, machines, t, HUMAN, A, lt, str(far_home / "src"), home.folder("here"), {}, False)
    assert far_tr.exists() and not list(home.projects.glob(f"*/{A}.jsonl"))


def test_transfer_refuses_another_machine_or_one_that_accepts_no_connections(home: Home, tmp_path: Path):
    tr = aged(home.transcript(A, home.folder("work")))
    fs, t, m = home.setup()
    lt, wrong, far_home = far_side(tmp_path, machine_id="0" * 32)
    with pytest.raises(Refused, match="far side"):
        transfer.send(fs, HOST, wrong, t, HUMAN, m.sessions[A], lt, str(far_home), None, True, lambda s: True)
    lt, closed, far_home = far_side(tmp_path / "2", ssh=None)
    with pytest.raises(Refused, match="accepts no connections"):
        transfer.send(fs, HOST, closed, t, HUMAN, m.sessions[A], lt, str(far_home), None, True, lambda s: True)
    with pytest.raises(Refused, match="full session ID"):
        transfer.fetch(fs, HOST, closed, t, HUMAN, "", lt, None, None, {}, True)
    assert tr.exists()


def test_move_refuses_what_it_cannot_do(home: Home):
    src, dst = home.folder("old"), home.folder("new")
    home.transcript(A, src)
    fs, t, m = home.setup()
    s = m.sessions[A]
    with pytest.raises(Refused, match="does not map to"):
        move_ops.plan(fs, HOST, t, s, dst, src=dst)
    with pytest.raises(Refused, match="does not exist"):
        move_ops.plan(fs, HOST, t, s, home.home / "missing", None)
    with pytest.raises(Refused, match="already filed under"):
        move_ops.plan(fs, HOST, t, s, src / "x" / "..", None)  # the same folder, written another way
    with pytest.raises(Refused, match="slug is"):
        move_ops.plan(fs, HOST, t, s, home.folder("d/" + "x" * 210), None)
    home.transcript(A, dst)  # a copy already where it would go: now under two slugs
    fs, t, m = home.setup()
    with pytest.raises(Refused, match="filed under 2 slugs"):
        move_ops.plan(fs, HOST, t, m.sessions[A], home.folder("third"), None)


def test_move_refuses_a_transcript_already_at_the_destination_and_clashing_folders(home: Home):
    src, dst = home.folder("old"), home.folder("new")
    tr = home.transcript(A, src)
    (home.projects / slug(dst)).mkdir()
    (tr.parent / A / "tool-results").mkdir(parents=True)
    (tr.parent / A / "tool-results" / "r1.txt").write_text("here")
    elsewhere = home.projects / slug(home.folder("cd"))  # a session that changed directory left results there
    (elsewhere / A / "tool-results").mkdir(parents=True)
    (elsewhere / A / "tool-results" / "r2.txt").write_text("there")
    fs, t, m = home.setup()
    plan = move_ops.plan(fs, HOST, t, m.sessions[A], dst, None)
    target = home.projects / slug(dst) / A  # the first <id>/ folder found is moved there, the other merged into it
    assert sum(b == target for _, b in plan.moves) == 1 and [b for _, b in plan.merges] == [target]
    (elsewhere / A / "tool-results" / "r1.txt").write_text("clash")
    with pytest.raises(Refused, match="both hold tool-results/r1.txt"):
        move_ops.plan(fs, HOST, t, m.sessions[A], dst, None)
    (home.projects / slug(dst) / f"{A}.jsonl").write_text("")
    fs, t, m = home.setup()
    with pytest.raises(Refused):
        move_ops.plan(fs, HOST, t, m.sessions[A], dst, None)
