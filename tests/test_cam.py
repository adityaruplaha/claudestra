"""The read side: slugs and redirects, trust and staff files, the model, the audit, the doctor checks."""

from __future__ import annotations

import json

from claudestra import checks
from claudestra.caller import transcript_problem
from claudestra.claude_fs import ClaudeFS
from claudestra.ops import audit
from claudestra.portable import slug
from claudestra.trust import load

from conftest import HOST, A, B, C, Home


def test_slug_is_lossy():
    assert slug("/home/u/a b") == slug("/home/u/a-b") == slug("/home/u/a.b") == "-home-u-a-b"


def test_drop_in_named_by_session(home: Home):
    home.staff_file(A, "one", {HOST: "~/w"})
    (home.config / "staff.d" / "two.yaml").write_text('name: "two"\nfolder: {}\ndescription: x\n')
    home.staff_file(B, "three", {HOST: "~/w"}, extra=f"session: {B}\n")
    t = load(HOST, home.home, home.config)
    assert [a.session for a in t.staff] == [A, B]
    assert t.staff[0].folder == home.home / "w"
    assert any("two.yaml" in e and "full ID" in e for e in t.errors)
    assert any("drop the session key" in e for e in t.errors)


def test_trust_scopes_and_protection(home: Home):
    home.trust(
        f"machines:\n  {HOST}:\n    home: /h\n    machine_id: x\n    protected:\n      - ~/lab\nsessions:\n  {A}:\n    scope: folder\n  {B}:\n    scope: manager\n"
    )
    t = load(HOST, home.home, home.config)
    assert t.scopes == {A: "folder"}
    assert any(B in e for e in t.errors)
    lab = home.home / "lab"
    assert t.is_protected(lab / "x")
    assert not t.is_protected(home.home / "labx")
    # By slug the test errs towards protecting: 'lab-x' and 'lab/x' share a slug.
    assert t.is_protected(None, slug(lab) + "-x")
    assert not t.is_protected(None, slug(home.home / "other"))
    # A folder named to slip past (one that only shares the protected folder's slug) still fails
    # the slug test (the review's H2).
    assert t.is_protected(home.home / "lab.d", slug(lab))


def test_model_names_folders_and_resolve(home: Home):
    w = home.folder("work")
    home.transcript(A, w)
    home.transcript(B, w)
    home.staff_file(A, "staffer-a", {HOST: "~/work"})
    _, _, m = home.setup()
    assert set(m.sessions) == {A, B}
    a = m.sessions[A]
    assert a.folder == w and a.staff_file is not None and a.name == f"name-{A[:4]}"
    assert m.resolve(A[:8]) == [a]
    assert m.resolve(A[:4]) == []  # under 8 characters is never a prefix
    assert m.resolve(f"name-{B[:4]}") == [m.sessions[B]]


def test_folder_must_be_the_one_its_session_is_filed_under(home: Home):
    """Resuming from any other folder forks a session, so a narrower folder is refused;
    and two folders sharing a slug are told apart by the folder the session started in."""
    top = home.folder("course")
    home.folder("course/project-1")
    home.folder("x/a-b")
    home.folder("x/a/b")
    home.transcript(A, top)
    home.transcript(B, top)
    home.transcript(C, home.home / "x/a-b")
    home.staff_file(A, "exact", {HOST: "~/course"})
    home.staff_file(B, "narrow", {HOST: "~/course/project-1"})
    home.staff_file(C, "collides", {HOST: "~/x/a/b"})
    fs = ClaudeFS(home.home)
    t = load(HOST, home.home, home.config)
    assert transcript_problem(fs, HOST, A, t.staff_file(A).folder) is None
    assert "staff file is out of date" in transcript_problem(fs, HOST, B, t.staff_file(B).folder)
    assert "shares a slug" in transcript_problem(fs, HOST, C, t.staff_file(C).folder)


def test_audit_forks_two_homes_orphans_and_redirects(home: Home):
    w, x = home.folder("w"), home.folder("x")
    shared = {
        "type": "user",
        "uuid": "shared-1",
        "sessionId": A,
        "cwd": str(w),
        "origin": {"kind": "human"},
        "message": {"content": "hi"},
    }
    home.transcript(A, w, [shared])
    home.transcript(
        B,
        w,
        [
            dict(shared, sessionId=B),
            {
                "type": "user",
                "uuid": "own-1",
                "sessionId": B,
                "origin": {"kind": "human"},
                "message": {"content": "more"},
            },
        ],
    )
    home.transcript(C, w)
    home.transcript(C, x)
    d = home.projects / slug(w)
    (d / "dddddddd-4444-4444-8444-444444444444").mkdir()
    (d / f"{A}.jsonl.superseded-2026").write_text("")
    (home.home / ".claude" / "file-history" / "eeeeeeee-5555-4555-8555-555555555555").mkdir(parents=True)
    second = home.projects / slug(home.folder("ws/second"))
    second.mkdir()
    (second / ".session-aliases").write_text(str(d))
    gone = home.projects / slug(home.folder("ws/third"))
    gone.mkdir()
    (gone / ".session-aliases").write_text(str(home.projects / "-nowhere"))
    fs, _, m = home.setup()
    forks = audit.forks(fs, m)
    assert {f.subject for f in forks} >= {A, B}
    assert any(f.subject == B and "1 its own, 1 of them typed" in f.detail for f in forks)
    assert [f.subject for f in audit.two_homes(fs, m)] == [C]
    orphans = {f.subject for f in audit.orphans(fs, m)}
    assert f"{slug(w)}/dddddddd-4444-4444-8444-444444444444" in orphans
    assert f"{slug(w)}/{A}.jsonl.superseded-2026" in orphans
    assert "file-history/eeeeeeee-5555-4555-8555-555555555555" in orphans
    assert second.name not in orphans and gone.name not in orphans
    assert [f.subject for f in audit.redirects(fs, m)] == [gone.name]


def test_redirects_are_followed(home: Home):
    first, second = home.folder("ws/first"), home.folder("ws/second")
    tr = home.transcript(A, second, slug_name=slug(first))
    (home.projects / slug(second)).mkdir()
    (home.projects / slug(second) / ".session-aliases").write_text(str(tr.parent))
    home.staff_file(A, "ws staffer", {HOST: "~/ws/second"})
    fs, t, m = home.setup()
    assert fs.filed_slug(second) == slug(first)
    assert m.sessions[A].folder == second
    assert transcript_problem(fs, HOST, A, t.staff_file(A).folder) is None


def test_checks_on_fixture(home: Home):
    w = home.folder("w")
    home.transcript(A, w)
    home.transcript(B, w, [{"type": "user", "uuid": "x", "sessionId": A}, {"type": "brand-new"}])
    fs = ClaudeFS(home.home, proc=home.home / "no-proc")
    by = {r.name: r for r in checks.run(fs, ["pid-files", "transcript-ids", "record-types"], deep=True)}
    assert by["pid-files"].status == checks.NA
    assert by["transcript-ids"].status == checks.FAIL
    assert by["record-types"].status == checks.WARN and "brand-new" in by["record-types"].detail
    assert checks.require(fs, []) == []  # a command that needs no check runs none


def test_subagents_forked_resumed_and_linked(home: Home):
    """Forked subagents open with a fork-context-ref; resumed ones start under an earlier ID; a
    continued session may read a subagent through a symlink (DESIGN.md §3)."""
    w = home.folder("w")
    ta, tb = home.transcript(A, w), home.transcript(B, w)
    rec = lambda sid: json.dumps({"type": "assistant", "isSidechain": True, "sessionId": sid})  # noqa: E731
    real = ta.parent / A / "subagents"
    real.mkdir(parents=True)
    (real / "staffer-fork.jsonl").write_text(json.dumps({"type": "fork-context-ref"}) + "\n" + rec(A) + "\n")
    (real / "staffer-resumed.jsonl").write_text(f"{rec(C)}\n{rec(A)}\n")
    (real / "staffer-x.jsonl").write_text(rec(B) + "\n")
    linked = tb.parent / B / "subagents"
    linked.mkdir(parents=True)
    (linked / "staffer-x.jsonl").symlink_to(real / "staffer-x.jsonl")
    fs, _, m = home.setup()
    assert checks.run(fs, ["subagents", "record-types"], deep=True)[0].status == checks.PASS
    sub = audit.subagents(fs, m)
    assert [f.subject for f in sub] == [f"{A}/subagents/staffer-x.jsonl"] and "through a symlink" in sub[0].detail
    assert [f.subject for f in audit.links(fs, m)] == [f"projects/{tb.parent.name}/{B}/subagents/staffer-x.jsonl"]
    (real / "staffer-x.jsonl").unlink()  # a dangling link is reported, never a crash
    fs, _, m = home.setup()
    assert "DANGLING" in audit.links(fs, m)[0].detail
    assert checks.run(fs, ["subagents"], deep=True)[0].status == checks.PASS
