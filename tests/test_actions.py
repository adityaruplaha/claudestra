"""The changing actions on a session: Rename, Type, Start, Stop, and who may take them (permissions.py)."""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path

import pytest

from claudestra.actions import permissions as perm
from claudestra.caller import Caller, Refused
from claudestra.runners import tmux as runner
from claudestra.session import Session, Staffer

from conftest import HERE, HUMAN, A, B, C, D, Home

R = {v: getattr(r, "allowed", None) or getattr(r, "kinds", frozenset()) for v, r in perm.matrix().items()}  # by verb

needs_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake = tmp_path / "claude"
    # Records its arguments and environment, then waits; exits on Ctrl-C, as Claude Code does.
    fake.write_text(
        f'#!/bin/sh\necho "$@" > {tmp_path}/argv\nenv > {tmp_path}/env\ntrap "exit 0" INT\nwhile :; do sleep 1; done\n'
    )
    fake.chmod(0o755)
    # The caller's own Claude variables, which must never reach a staffer.
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "caller-session")
    monkeypatch.setattr(runner, "STARTUP_WAIT", 1.0)
    socket = f"camtest-{uuid.uuid4().hex[:8]}"
    yield socket, tmp_path, str(fake)
    runner.Tmux(socket).server.cmd("kill-server")


def no(plan: list[str]) -> bool:
    """A go_ahead that only records the plan, as a dry run does."""
    no.plan = plan
    return False


# --- who may: the relation and the table ------------------------------------------------------------


def test_relations_and_the_table(home: Home):
    """Each relation, from the same code as `managed by`, and what the table lets it do."""
    top = home.folder("top")
    for sid, folder in ((A, top), (B, home.folder("top/sub")), (C, home.folder("loose"))):
        home.transcript(sid, folder)
    home.staff_file(A, "mgr", {HERE: "~/top"})
    home.staff_file(B, "inner", {HERE: "~/top/sub"})
    home.staff_file(C, "loose", {HERE: "~/loose"})
    D = "dddddddd-4444-4444-8444-444444444444"
    home.transcript(D, home.folder("plain"))  # a session that is no staffer
    home.acting(HUMAN, {A: "folder"})
    mgr = Caller("folder", A, "mgr", 1, folder=top)
    dev = Caller("device", "eeeeeeee-5555-4555-8555-555555555555", "dev", 1)
    inner, loose, plain, a = Session(B), Session(C), Session(D), Session(A)
    assert perm.relation(HUMAN, inner) == perm.USER
    assert perm.relation(mgr, inner) == perm.MANAGER and perm.relation(mgr, loose) == perm.NONE
    assert perm.relation(mgr, a) == perm.SELF
    assert perm.relation(dev, a) == perm.D_MANAGER
    assert perm.relation(dev, inner) == perm.D_MANAGED and perm.relation(dev, loose) == perm.D_UNMANAGED
    assert perm.relation(dev, plain) == perm.D_OTHER
    perm.require_on_session("start", dev, loose, R["start"])  # no manager holds it: the device scope's
    with pytest.raises(Refused, match="device over a managed specialist"):
        perm.require_on_session("start", dev, inner, R["start"])  # its manager starts it
    perm.require_on_session("rename", dev, inner, R["rename"])
    perm.require_on_session("type", mgr, inner, R["type"])
    with pytest.raises(Refused, match="may not trash itself"):
        perm.require_on_session("trash", mgr, a, R["trash"])
    with pytest.raises(Refused, match="needs one of"):
        perm.require_on_session("rename", dev, plain, R["rename"])  # a session that is no staffer: the user's alone


def test_him_under_claude_is_restricted(home: Home):
    """The user at a terminal with Claude in the chain is restricted mode: what needs the user is refused."""
    from claudestra.proctree import ClaudeProc, Proc

    home.transcript(A, home.folder("w"))
    claude = ClaudeProc(Proc(30, 1, "1030", "claude", "/usr/bin/claude"), None, 2)
    c = home.acting(HUMAN, chain=[claude])
    assert c.restricted and perm.relation(HUMAN, Session(A)) == perm.NONE
    with pytest.raises(Refused, match="restricted mode"):
        Session(A).rename("new").perform()
    with pytest.raises(Refused, match="restricted mode"):
        perm.require_kind("purge", HUMAN, R["purge"])


# --- rename ---------------------------------------------------------------------------------------


def test_rename_a_stopped_session_as_slash_rename_does(home: Home):
    tr = home.transcript(A, home.folder("w"))
    tr.write_bytes(tr.read_bytes().rstrip(b"\n"))  # cut by a crash: no last newline
    home.staff_file(A, "old name", {HERE: "~/w"})
    home.staff_file(B, "taken", {HERE: "~/w"})
    home.acting(HUMAN)
    with pytest.raises(Refused, match="already named"):
        Session(A).rename("taken").perform()
    assert Session(A).rename("  [x] new  ").perform(no) is None and "'name-aaaa' -> '[x] new'" in no.plan[0]
    Session(A).rename("  [x] new  ").perform()
    recs = [json.loads(x) for x in tr.read_text().splitlines()]
    assert recs[-2:] == [
        {"type": "custom-title", "customTitle": "[x] new", "sessionId": A},
        {"type": "agent-name", "agentName": "[x] new", "sessionId": A},
    ]
    assert json.loads((tr.parent / A / "custom-title.json").read_text()) == {"customTitle": "[x] new"}
    assert Session(A).name == "[x] new" and Staffer(A).staff_file.name == "[x] new"


def test_rename_changes_only_the_drop_ins_name_line(home: Home):
    """The rest of the staff file stays as its staffer wrote it: comments, quoting, folded text."""
    home.transcript(A, home.folder("w"))
    f = home.config / "staff.d" / f"{A}.yaml"
    f.write_text(
        f'# Written by the staffer itself.\nname: "old"\nfolder:\n  {HERE}: ~/w\ndescription: >-\n  Folded over\n  two lines.\n'
    )
    before = f.read_text().splitlines()
    home.acting(HUMAN)
    Session(A).rename('say "hi" [x]').perform()
    after = f.read_text().splitlines()
    assert [i for i, (x, y) in enumerate(zip(before, after, strict=True)) if x != y] == [1]
    assert (
        Staffer(A).staff_file.name == 'say "hi" [x]' and Staffer(A).staff_file.description == "Folded over two lines."
    )


def test_rename_undo_puts_the_old_name_back(home: Home):
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "before", {HERE: "~/w"})
    home.acting(HUMAN)
    action = Session(A).rename("after")
    action.perform()
    assert Session(A).name == "after" and action.reversible
    action.undo()
    assert Session(A).name == "name-aaaa" and Staffer(A).staff_file.name == "before"  # each as it was


# --- start and stop -----------------------------------------------------------------------------------


@needs_tmux
def test_start_refuses_without_remote_control(home: Home, server):
    socket, tmp, claude = server
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "[x] one", {HERE: "~/w"})
    home.settings.write_text("{}")
    home.acting(HUMAN)
    with pytest.raises(Refused, match="remote-control"):
        Session(A).start(claude, socket).perform()


def test_start_then_stop(home: Home, server):
    socket, tmp, claude = server
    home.transcript(A, home.folder("w"))
    home.transcript(B, home.folder("w"))
    home.staff_file(A, "[x] one", {HERE: "~/w"})
    home.acting(HUMAN)
    one = Session(A)
    assert one.start(claude, socket).perform(no) is None and no.plan[0].startswith("would start")
    assert one.start(claude, socket).perform().startswith("started   [x] one")
    for _ in range(50):
        if (tmp / "env").exists():
            break
        time.sleep(0.1)
    assert (tmp / "argv").read_text().split()[:4] == ["--resume", A, "--remote-control", "[x]"]
    assert not [line for line in (tmp / "env").read_text().splitlines() if line.startswith("CLAUDE")]
    path = next(line for line in (tmp / "env").read_text().splitlines() if line.startswith("PATH="))
    assert path.split("=", 1)[1].split(":")[0] == str(Path(claude).parent)  # claude's folder first
    w = runner.Tmux(socket).window(A)
    assert w and not w.dead
    assert one.start(claude, socket).perform() == "running   [x] one"
    assert one.stop(socket=socket).perform() == "stopped   [x] one"
    assert runner.Tmux(socket).window(A) is None


@needs_tmux
def test_stop_clears_an_exited_window_and_a_dry_run_only_says_so(home: Home, server, tmp_path: Path):
    socket, _, _ = server
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    home.acting(HUMAN)
    quits = tmp_path / "claude-quits"
    quits.write_text("#!/bin/sh\nexit 0\n")
    quits.chmod(0o755)
    assert Session(A).start(str(quits), socket).perform().startswith("exited")
    assert Session(A).stop(socket=socket).perform(no) is None and no.plan[0].startswith("would clear  one")
    assert runner.Tmux(socket).window(A) is not None
    assert Session(A).stop(socket=socket).perform().startswith("cleared   one")
    assert runner.Tmux(socket).window(A) is None


@needs_tmux
def test_start_any_session_whose_folder_is_known_but_off_the_staff_only_he_does(home: Home, server):
    socket, _, _ = server
    home.transcript(A, home.folder("w"))
    home.transcript(B, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    c = home.acting(HUMAN)
    with pytest.raises(Refused, match="reinstall"):
        Session(A).start("/nowhere/claude", socket).perform()
    with pytest.raises(Refused, match="reinstall"):  # off the staff, but the user's to start: past every check
        Session(B).start("/nowhere/claude", socket).perform()
    assert Session(B).launch.name == f"name-{B[:4]}" and Staffer(A).launch.name == "one"
    c._subject = Caller("device", C, "d", 1)
    with pytest.raises(Refused, match="device over a session not on the staff"):
        Session(B).start("/nowhere/claude", socket).perform()
    home.transcript(D, home.folder("v"), [], slug_name="-somewhere-unknown")  # no folder known to file there
    c._subject = HUMAN
    with pytest.raises(Refused, match="folder .* is filed under is not known"):
        Session(D).start("/nowhere/claude", socket).perform()


# --- type, and rename by typing ----------------------------------------------------------------------


@needs_tmux
def test_type_and_rename_a_running_staffer(home: Home, tmp_path: Path):
    """Refused while text is typed and unsent; otherwise /rename is typed, and the staff file follows."""
    tr = home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    home.transcript(C, home.home)
    home.staff_file(C, "mgr", {HERE: "~/"})  # the manager over ~/w; a bare ~ is YAML for null
    sessions = home.home / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    title = tr.parent / A / "custom-title.json"
    fake = tmp_path / "claude-renaming"
    # A stand-in that registers a live session file, shows a prompt with a dimmed suggestion, and
    # writes custom-title.json when it reads /rename, as Claude Code does.
    fake.write_text(f"""#!/bin/sh
start=$(awk '{{print $22}}' /proc/$$/stat)
printf '{{"pid":%s,"sessionId":"%s","procStart":"%s","status":"idle","kind":"interactive","cwd":"%s"}}' $$ "$2" "$start" "$PWD" > {sessions}/$$.json
trap 'rm {sessions}/$$.json; exit 0' INT
mkdir -p {title.parent}
printf '\\342\\235\\257 \\033[2mpush it\\033[0m\\n'
while IFS= read -r line; do
  case "$line" in /rename\\ *) printf '{{"customTitle":"%s"}}' "${{line#/rename }}" > {title};; esac
  printf '\\342\\235\\257 '
done
""")
    fake.chmod(0o755)
    socket = f"camtest-{uuid.uuid4().hex[:8]}"
    t = runner.Tmux(socket)
    try:
        c = home.acting(HUMAN, {C: "folder"})
        assert Session(A).start(str(fake), socket).perform().startswith("started")
        c.refresh()
        w = t.window(A)
        mgr = Caller("folder", C, "mgr", 1, folder=home.home)
        c._subject = mgr  # its manager types into it, and renames it
        assert Session(A).type("hello", socket).perform(no) is None and f"window {w.id}" in no.plan[0]
        with pytest.raises(Refused, match="one line"):
            Session(A).type("two\nlines", socket).perform()
        c._subject = Caller("folder", B, "f", 1, folder=home.home)  # a folder scope that does not manage it
        with pytest.raises(Refused, match="relation to it is none"):
            Session(A).type("hello", socket).perform()
        c._subject = HUMAN
        t.run("send-keys", "-t", w.id, "-l", "half typed")
        time.sleep(0.3)
        with pytest.raises(Refused, match="unsent text"):
            Session(A).rename("[x] two", socket).perform()
        t.run("send-keys", "-t", w.id, "Enter")
        time.sleep(0.3)
        c._subject = mgr
        Session(A).rename("[x] two", socket).perform()
        assert json.loads(title.read_text()) == {"customTitle": "[x] two"}
        assert Staffer(A).staff_file.name == "[x] two"
        assert t.window(A) is not None  # named by its session ID, so the rename does not lose it
        c._subject = HUMAN
        assert Session(A).stop(socket=socket).perform().startswith("stopped")
    finally:
        t.server.cmd("kill-server")


# --- move, trash, restore and purge -----------------------------------------------------------------


def test_move_trash_and_restore_permissions(home: Home):
    """Moving a staffer is the user's or a device scope's over a manager; a staffer is never trashed;
    restoring is the user's or a device scope's; purging is the user's alone."""
    from conftest import aged

    lab = home.folder("lab")
    aged(home.transcript(A, lab))
    aged(home.transcript(B, home.folder("plain")))  # a session that is no staffer
    home.staff_file(A, "a", {HERE: "~/lab"})
    c = home.acting(Caller("unscoped", C, "x", 1))
    with pytest.raises(Refused, match="relation to it is none"):
        Session(A).move(home.folder("elsewhere")).perform()
    c._subject = Caller("device", C, "d", 1)
    with pytest.raises(Refused, match="on the staff; dismiss it first"):
        Session(A).trash(0).perform()  # a staffer is dismissed before its session is trashed
    entry = Session(B).trash(0).perform()  # a session that is no staffer: a device scope may
    assert entry is not None and not Session(B).here
    c._subject = Caller("folder", C, "f", 1, folder=lab)
    with pytest.raises(Refused, match="restore is for"):
        c.restore(B).perform()
    with pytest.raises(Refused, match="purge is for"):
        c.purge(1).perform()
    c._subject = Caller("device", C, "d", 1)
    assert c.restore(B[:8]).perform() and Session(B).here


def test_undo_puts_a_move_and_a_trash_back(home: Home):
    from conftest import aged

    w, x = home.folder("w"), home.folder("x")
    aged(home.transcript(A, w))
    home.acting(HUMAN)
    move = Session(A).move(x)
    move.perform()
    assert Session(A).folder == x and move.reversible
    move.undo()
    assert Session(A).folder == w
    trash = Session(A).trash(0)
    trash.perform()
    assert not Session(A).here
    trash.undo()
    assert Session(A).here


# --- transactions -------------------------------------------------------------------------------------


def test_a_transaction_is_all_or_nothing(home: Home, monkeypatch: pytest.MonkeyPatch):
    from claudestra.actions.base import Transaction
    from claudestra.actions.type import Type

    from conftest import aged

    aged(home.transcript(A, home.folder("w")))
    aged(home.transcript(B, home.folder("w")))
    home.staff_file(A, "a", {HERE: "~/w"})
    home.staff_file(B, "b", {HERE: "~/w"})
    home.acting(HUMAN)
    with pytest.raises(Refused, match="may only be a transaction's last step"):
        Transaction([Type(Session(A), "hi"), Session(B).rename("x")])
    first, second = Session(A).rename("a2"), Session(B).rename("b2")
    original = second.run

    def fail() -> None:
        raise Refused("the disk is full")

    monkeypatch.setattr(second, "run", fail)
    with pytest.raises(Refused, match="disk is full"):
        Transaction([first, second]).perform()
    assert Staffer(A).staff_file.name == "a" and Session(A).name == "name-aaaa"  # the first was undone
    monkeypatch.setattr(second, "run", original)
    Transaction([Session(A).rename("a2"), Session(B).rename("b2")]).perform()
    assert (Session(A).name, Session(B).name) == ("a2", "b2")


def test_the_login_unit_starts_only_this_machines_autostart_staffers(home: Home):
    for sid in (A, B):
        home.transcript(sid, home.folder("w"))
    home.staff_file(A, "mgr", {HERE: "~/w"})
    home.staff_file(B, "other", {HERE: "~/w"})
    home.acting(HUMAN)
    home.trust(
        home.config.joinpath("trust.yaml")
        .read_text()
        .replace("    home:", f"    autostart:\n      - {A}\n    home:", 1)
    )
    from claudestra.context import Context

    Context.current().refresh()
    login = Caller("login")
    assert perm.relation(login, Session(A)) == perm.LOGIN_AUTOSTART
    perm.require_on_session("start", login, Session(A), R["start"])
    with pytest.raises(Refused, match="needs one of"):
        perm.require_on_session("start", login, Session(B), R["start"])
    with pytest.raises(Refused, match="needs one of"):
        perm.require_on_session("stop", login, Session(A), R["stop"])


def test_every_changing_action_declares_who_may_take_it():
    """Each action states its own rule; nothing changing is left without one."""
    assert set(R) == {
        "attach", "compact", "describe", "dismiss", "fetch", "fix the audit", "guard", "hire", "install", "move", "purge", "rename",
        "fix-name", "remote-control", "restore", "send", "start", "stop", "trash", "type",
        "trust grant", "trust revoke", "trust autostart", "trust protect", "trust machine",
    }  # fmt: skip
    # the audit's fixes are each authorized as their own verb; the guard only adds protection
    assert all(R[v] for v in R if v not in ("fix the audit", "guard"))
    assert R["send"] == {perm.USER} and R["restore"] == {"human", "device"}


# --- audit --fix --------------------------------------------------------------------------------


def _retitle(tr: Path, sid: str, name: str) -> None:
    """A /rename typed inside the session: the title changes, the staff file does not."""
    with tr.open("a") as fh:
        fh.write(json.dumps({"type": "custom-title", "customTitle": name, "sessionId": sid}) + "\n")


def test_audit_fix_brings_drop_in_names_into_step(home: Home):
    from claudestra.actions.audit import Audit
    from claudestra.actions.fix_audit import FixAudit

    lab = home.folder("lab")
    ta, tb, tc = (home.transcript(sid, home.folder(f"lab/{n}")) for sid, n in ((A, "a"), (B, "b"), (C, "c")))
    home.staff_file(A, "a", {HERE: "~/lab/a"})
    home.staff_file(B, "b", {HERE: "~/lab/b"})
    home.staff_file(C, "c", {HERE: "~/lab/c"})
    _retitle(ta, A, "a renamed")
    _retitle(tb, B, "b renamed")
    _retitle(tc, C, "b")  # would clash with b's staff file name, so it is skipped
    c = home.acting(Caller("unscoped", A, "a", 1))  # a staffer fixes its own staff file, and nothing else
    assert {f.subject for f in Audit(["names"]).perform()["names"]} == {A, B, C}
    action = FixAudit()
    assert action.perform(no) is None
    assert "staff file" in no.plan[0] and "'a' -> 'a renamed'" in no.plan[0]
    assert any(f"skip {B}" in line for line in no.plan) and any("already named 'b'" in line for line in no.plan)
    assert len(FixAudit().perform()) == 1
    assert Staffer(A).staff_file.name == "a renamed" and Staffer(B).staff_file.name == "b"
    c._subject = HUMAN
    assert len(FixAudit().perform()) == 1  # b now; c still clashes with b's old name until b moves
    assert Staffer(B).staff_file.name == "b renamed"
    assert len(FixAudit().perform()) == 1 and Staffer(C).staff_file.name == "b"
    assert Audit(["names"]).perform()["names"] == []
    del lab


# --- claudestra trust ---------------------------------------------------------------------------------


def test_trust_commands_write_their_own_layout_and_undo(home: Home):
    import yaml

    from claudestra.actions.trust_autostart import TrustAutostart
    from claudestra.actions.trust_grant import TrustGrant
    from claudestra.actions.trust_machine import TrustMachine
    from claudestra.actions.trust_protect import TrustProtect
    from claudestra.actions.trust_revoke import TrustRevoke
    from claudestra.actions.trust_show import TrustShow
    from claudestra.context import Context

    home.transcript(A, home.folder("w"))
    home.staff_file(A, "mgr", {HERE: "~/w"})
    c = home.acting(HUMAN)
    f = home.config / "trust.yaml"
    grant = TrustGrant(A, "folder")
    grant.perform()
    text = f.read_text()
    assert text.startswith("# Written by `claudestra trust`") and f"  {A}: # mgr\n    scope: folder" in text
    assert Context.current().trust.scope(A) == "folder"
    TrustAutostart(A, add=True).perform()
    TrustProtect(home.folder("lab"), add=True).perform()
    raw = yaml.safe_load(f.read_text())
    assert raw["machines"][HERE]["autostart"] == [A] and raw["machines"][HERE]["protected"] == ["~/lab"]
    assert f"      - {A} # mgr" in f.read_text() and TrustShow().perform() == f.read_text()
    with pytest.raises(Refused, match="already has folder scope"):
        TrustGrant(A, "folder").perform()
    with pytest.raises(Refused, match="give .* --home and --machine-id"):
        TrustMachine(add=True, host="far").perform()
    TrustMachine(add=True, host="far", home=Path("/home/far"), machine_id="abc", ssh="u@far").perform()
    assert yaml.safe_load(f.read_text())["machines"]["far"] == {
        "home": "/home/far",
        "machine_id": "abc",
        "ssh": "u@far",
    }
    revoke = TrustRevoke(A)
    revoke.perform()
    assert Context.current().trust.scope(A) is None
    revoke.undo()
    assert Context.current().trust.scope(A) == "folder"
    c._subject = Caller("device", B, "d", 1)
    with pytest.raises(Refused, match="is for the user"):
        TrustRevoke(A).perform()  # changing trust is the user's alone


def test_audit_errors_are_typed_and_say_whether_they_can_be_fixed(home: Home):
    from claudestra.actions.audit import Audit
    from claudestra.actions.set_staff_name import SetStaffName
    from claudestra.audit_errors import NameMismatch, Orphan

    tr = home.transcript(A, home.folder("w"))
    home.staff_file(A, "a", {HERE: "~/w"})
    _retitle(tr, A, "a renamed")
    (tr.parent / "dddddddd-4444-4444-8444-444444444444").mkdir()  # a session folder with no transcript
    home.acting(HUMAN)
    found = Audit(["names", "orphans"]).perform()
    [mismatch], [orphan] = found["names"], found["orphans"]
    assert isinstance(mismatch, NameMismatch) and isinstance(mismatch.fix(), SetStaffName)
    assert isinstance(orphan, Orphan) and orphan.fix() is None  # left for the user to settle


def test_a_failed_undo_does_not_hide_the_failure_or_stop_the_other_undos(home: Home, monkeypatch: pytest.MonkeyPatch):
    from claudestra.actions.base import Transaction

    for sid in (A, B, C):
        home.transcript(sid, home.folder("w"))
    home.staff_file(A, "a", {HERE: "~/w"})
    home.staff_file(B, "b", {HERE: "~/w"})
    home.staff_file(C, "c", {HERE: "~/w"})
    home.acting(HUMAN)
    first, second, third = Session(A).rename("a2"), Session(B).rename("b2"), Session(C).rename("c2")

    def boom(*a) -> None:
        raise Refused("the disk is full")

    def stuck(*a) -> None:
        raise Refused("cannot put it back")

    monkeypatch.setattr(third, "run", boom)
    monkeypatch.setattr(second, "undo", stuck)
    with pytest.raises(Refused, match="the disk is full; and these could not be undone: rename: cannot put it back"):
        Transaction([first, second, third]).perform()
    assert Staffer(A).staff_file.name == "a"  # the first was still undone, after the second's undo failed


# --- hire and dismiss ------------------------------------------------------------------------------


def test_hire_writes_the_staff_file_and_dismiss_moves_it_aside_with_its_scope_waiting(home: Home):
    import uuid

    from claudestra.trust import STAFF_HEADER

    socket = f"camtest-{uuid.uuid4().hex[:8]}"  # no server there: nothing is running
    w = home.folder("w")
    home.transcript(A, w)
    c = home.acting(HUMAN, {})
    with pytest.raises(Refused, match="description says what it works on"):
        Session(A).hire().perform()
    Session(A).hire(description="Works on w.").perform()
    f = home.config / "staff.d" / f"{A}.yaml"
    assert f.read_text().startswith(STAFF_HEADER) and Staffer(A).staff_name == f"name-{A[:4]}"
    assert Staffer(A).launch.folder == w and Staffer(A).staff_file.description == "Works on w."
    with pytest.raises(Refused, match="on the staff already"):
        Session(A).hire(description="again").perform()
    with pytest.raises(Refused, match="dismiss it first"):
        Session(A).trash(0).perform()
    # A scope, then a dismissal: the scope waits in trust.yaml, and comes back with a rehire.
    home.trust((home.config / "trust.yaml").read_text() + f"sessions:\n  {A}:\n    scope: folder\n")
    c.refresh()
    assert Staffer(A).scope == "folder"
    Staffer(A).dismiss(socket).perform()
    assert not f.exists() and (home.config / "staff-dismissed.d" / f"{A}.yaml").exists()
    assert not c.trust.errors and c.trust.scope(A) is None and c.trust.scopes[A] == "folder"
    Session(A).hire(name="rehired").perform()  # description and folders from the dismissed file
    assert Staffer(A).staff_name == "rehired" and Staffer(A).scope == "folder"
    assert Staffer(A).staff_file.description == "Works on w."
    assert not (home.config / "staff-dismissed.d" / f"{A}.yaml").exists()


def test_who_may_hire_and_dismiss(home: Home):
    import uuid

    socket = f"camtest-{uuid.uuid4().hex[:8]}"
    top, loose = home.folder("top"), home.folder("loose")
    home.transcript(A, top)
    home.transcript(B, home.folder("top/sub"))
    home.transcript(C, loose)
    home.transcript(D, home.folder("loose/x"))
    home.staff_file(A, "mgr", {HERE: "~/top"})
    c = home.acting(HUMAN, {A: "folder"})
    with pytest.raises(Refused, match="may not hire itself"):
        c._subject = Caller("unscoped", C, "c", 1)
        Session(C).hire(description="me").perform()
    c._subject = Caller("folder", A, "mgr", 1, folder=top)
    Session(B).hire(description="under mgr").perform()  # a manager hires into its own folder
    with pytest.raises(Refused, match="relation to it is none"):
        Session(C).hire(description="not its folder").perform()
    c._subject = Caller("device", "eeeeeeee-5555-4555-8555-555555555555", "dev", 1)
    with pytest.raises(Refused, match="device over a managed specialist"):
        Staffer(B).dismiss(socket).perform()  # under a manager: the manager's to dismiss
    Session(C).hire(description="loose").perform()  # no manager holds ~/loose: the device scope's
    Staffer(C).dismiss(socket).perform()
    with pytest.raises(Refused, match="device over a manager"):
        Staffer(A).dismiss(socket).perform()
    c._subject = Caller("folder", A, "mgr", 1, folder=top)
    Staffer(B).dismiss(socket).perform()
    c._subject = HUMAN
    home.trust((home.config / "trust.yaml").read_text().replace("sessions:", f"    autostart:\n      - {A}\nsessions:"))
    c.refresh()
    with pytest.raises(Refused, match="autostart first"):
        Staffer(A).dismiss(socket).perform()


def test_trust_grant_needs_a_staffer(home: Home):
    from claudestra.actions.trust_grant import TrustGrant

    home.transcript(A, home.folder("w"))
    home.acting(HUMAN)
    with pytest.raises(Refused, match="not on the staff; a scope is a staffer's"):
        TrustGrant(A, "folder").perform()


def test_an_action_must_say_who_may_take_it_and_how_it_is_undone():
    from claudestra.actions.base import Action

    with pytest.raises(TypeError, match="does not declare who"):
        type("Nameless", (Action,), {"verb": "nameless"})
    with pytest.raises(TypeError, match="reversible but has no undo"):
        type("OneWay", (Action,), {"verb": "one-way", "who": perm.Anyone(), "reversible": True})


def test_attach_never_takes_the_lock(home: Home, monkeypatch: pytest.MonkeyPatch):
    from claudestra.actions import base
    from claudestra.actions.attach import Attach

    home.acting(HUMAN)
    monkeypatch.setattr(base, "locked", lambda: pytest.fail("Attach took the lock"))
    ran = []
    monkeypatch.setattr(Attach, "run", lambda self: ran.append(1))
    Attach("camtest-none").perform()
    assert ran == [1]


def test_a_staffer_keeps_its_own_description_current(home: Home):
    home.transcript(A, home.folder("w"))
    home.transcript(B, home.folder("w/sub"))
    home.staff_file(A, "mgr", {HERE: "~/w"})
    home.staff_file(B, "spec", {HERE: "~/w/sub"})
    c = home.acting(Caller("folder", A, "mgr", 1, folder=home.folder("w")), {A: "folder"})
    Staffer(A).set_description("Runs the w project.").perform()  # its own
    assert Staffer(A).staff_file.description == "Runs the w project."
    Staffer(B).set_description("Something else.").perform()  # its manager states its specialist's work
    assert Staffer(B).staff_file.description == "Something else."
    c._subject = Caller("device", C, "dev", 1)
    with pytest.raises(Refused, match="device over a manager"):
        Staffer(A).set_description("Not the device scope's to say.").perform()
    c._subject = Caller("unscoped", B, "spec", 1)
    action = Staffer(B).set_description("  Works on sub.  ")
    action.perform()
    assert Staffer(B).staff_file.description == "Works on sub."
    with pytest.raises(Refused, match="already has that description"):
        Staffer(B).set_description("Works on sub.").perform()
    action.undo()
    assert Staffer(B).staff_file.description == "Something else."


def test_move_requires_the_jobs_check_since_it_rewrites_job_state():
    from claudestra.actions.move import Move

    assert "jobs" in Move.needs and "transcript-ids" in Move.needs
