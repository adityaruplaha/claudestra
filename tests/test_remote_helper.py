"""The helper the other machine runs, called in-process here with its home pointed at a fixture folder. The
transfer tests run it as the far side does, in a subprocess, where coverage cannot see it; these check its
refusals directly: nothing outside ~/.claude, no symlink followed at the end of a path, memory only read."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claudestra import portable
from claudestra import remote_helper as rh

from conftest import A, B, C


@pytest.fixture
def far(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "far"
    root = home / ".claude"
    (root / "projects" / "-w").mkdir(parents=True)
    for name, value in {"HOME": home, "ROOT": root, "PROJECTS": root / "projects", "PROC": home / "proc"}.items():
        monkeypatch.setattr(rh, name, value)
    return root


def refused(fn, *a) -> str:
    with pytest.raises(SystemExit) as e:
        fn(*a)
    return json.loads(str(e.value))["error"]


def test_safe_refuses_paths_out_of_claude_and_writes_into_memory(far: Path, tmp_path: Path):
    assert rh.safe("projects/-w/x.jsonl") == far / "projects" / "-w" / "x.jsonl"
    assert refused(rh.safe, "../.bashrc") == "refusing ../.bashrc"
    assert refused(rh.safe, "projects/../../x") == "refusing projects/../../x"
    for up in ("..", "projects/..", "projects/-w/../../.."):  # a last `..` is not resolved, so is refused outright
        assert refused(rh.safe, up) == f"refusing {up}"
    (far / "projects" / "out").symlink_to(tmp_path)  # a link out of ~/.claude, as a folder on the way
    assert refused(rh.safe, "projects/out/x") == "refusing projects/out/x"
    assert refused(rh.safe, "projects/-w/memory/MEMORY.md").startswith("refusing")
    assert rh.safe("projects/-w/memory/MEMORY.md", reading=True).name == "MEMORY.md"


def test_probe_finds_every_store_and_reports_the_machine(far: Path):
    p = far / "projects" / "-w"
    (p / f"{A}.jsonl").write_text("{}\n")
    (p / A).mkdir()
    (p / f"{A}.orphaned-1.jsonl").write_text("")
    (p / f"{A}.jsonl.superseded-1").write_text("")
    (far / "file-history" / A).mkdir(parents=True)
    (far / "file-history" / B).mkdir()
    got = rh.probe(
        {"sid": A, "keyed": ["file-history", "uploads"], "secondary": [B], "dirs": [str(p)], "filed": ["/w"]}
    )
    assert got["stores"] == [
        f"projects/-w/{A}.jsonl",
        f"projects/-w/{A}",
        f"projects/-w/{A}.orphaned-1.jsonl",
        f"projects/-w/{A}.jsonl.superseded-1",
        f"file-history/{A}",
        f"file-history/{B}",
    ]
    assert got["running"] is None and got["dirs"] == {str(p): True} and got["filed"] == {"/w": "-w"}
    assert got["machine_id"] == portable.machine_id() and got["home"] == str(rh.HOME)


def test_sha_and_list_skip_symlinks(far: Path, tmp_path: Path):
    d = far / "projects" / "-w" / A
    (d / "subagents").mkdir(parents=True)
    (d / "subagents" / "a.jsonl").write_text("x")
    (tmp_path / "elsewhere").write_text("secret")
    (d / "subagents" / "b.jsonl").symlink_to(tmp_path / "elsewhere")
    rel = f"projects/-w/{A}"
    assert rh.list_files({"stores": [rel]}) == {
        "files": [f"{rel}/subagents/a.jsonl"],
        "links": [f"{rel}/subagents/b.jsonl"],
    }
    sums = rh.sha({"files": [f"{rel}/subagents/a.jsonl", f"{rel}/subagents/b.jsonl", f"{rel}/missing"]})
    assert sums[f"{rel}/subagents/a.jsonl"] == portable.sha256(d / "subagents" / "a.jsonl")
    assert sums[f"{rel}/subagents/b.jsonl"] is None and sums[f"{rel}/missing"] is None
    assert refused(rh.list_files, {"stores": ["../"]}) == "refusing ../"


def test_trash_moves_the_stores_and_refuses_a_running_session(far: Path):
    t = far / "projects" / "-w" / f"{A}.jsonl"
    t.write_text("{}\n")
    got = rh.trash({"sid": A, "stores": [f"projects/-w/{A}.jsonl", "projects/-w/gone"], "slug": "-w"})
    entry = far / portable.TRASH / got["entry"]
    assert not t.exists() and (entry / "stores" / f"projects/-w/{A}.jsonl").is_file()
    (far / "projects" / "-w" / "memory").mkdir()
    (far / "projects" / "-w" / "memory" / "x").write_text("kept")  # only a store that exists is moved
    assert refused(rh.trash, {"sid": C, "stores": ["projects/-w/memory/x"]}).startswith("refusing")
    assert (far / "projects" / "-w" / "memory" / "x").read_text() == "kept"
    assert refused(rh.trash, {"sid": C, "stores": ["projects/-w/../../.."]}).startswith("refusing")

    pid = 4242
    proc = rh.PROC / str(pid)
    proc.mkdir(parents=True)
    (proc / "stat").write_text(f"{pid} (claude) S 1 " + " ".join(["0"] * 17) + " 77 0\n")
    (far / "sessions").mkdir()
    (far / "sessions" / f"{pid}.json").write_text(json.dumps({"sessionId": B, "procStart": "77"}))
    assert refused(rh.trash, {"sid": B, "stores": []}) == f"{B} is running here"
    assert rh.probe({"sid": B})["running"] == pid


def test_log_appends_to_the_far_sides_state(far: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(far.parent / ".local" / "state"))  # as LocalTransport sets it
    assert rh.log({"entry": {"verb": "send"}}) == {}
    log = portable.state_dir(rh.HOME) / "log"
    assert log.is_relative_to(far.parent) and json.loads(log.read_text()) == {"verb": "send"}


def test_this_sides_guard_refuses_a_last_dotdot(tmp_path: Path):
    """ops/common.guard resolves a path's parent but not its last part, as safe() does, so it refuses `..`."""
    from claudestra.caller import Refused
    from claudestra.claude_fs import ClaudeFS
    from claudestra.ops import common

    fs = ClaudeFS(tmp_path / "home")
    (fs.projects / "-w").mkdir(parents=True)
    common.guard(fs, fs.projects / "-w" / "x.jsonl")
    with pytest.raises(Refused, match="outside ~/.claude"):
        common.guard(fs, fs.projects / "-w" / ".." / ".." / "..")
