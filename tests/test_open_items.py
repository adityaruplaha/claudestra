"""Open items: a manager's, written where it lives; who may change them; `list`'s scope by the chain of command;
ULIDs and their endings; reassigning within this machine; audit's report; staff history."""

from __future__ import annotations

import pytest
import yaml

from claudestra import portable
from claudestra.actions.open_items_add import OpenItemAdd
from claudestra.actions.open_items_delete import OpenItemDelete
from claudestra.actions.open_items_get import OpenItemGet
from claudestra.actions.open_items_list import OpenItemsList
from claudestra.actions.open_items_reassign import OpenItemReassign
from claudestra.actions.open_items_search import OpenItemsSearch
from claudestra.actions.open_items_update import OpenItemUpdate
from claudestra.actions.staff_history_list import StaffHistoryList
from claudestra.caller import Caller, Refused
from claudestra.context import Context
from claudestra.ops import audit
from claudestra.ops import open_items as items_ops
from claudestra.session import Session

from conftest import HERE, HUMAN, A, B, C, D, Home

E = "eeeeeeee-5555-4555-8555-555555555555"


def project(home: Home):
    """A manager A over ~/top, with specialist B in ~/top/sub, a sub-manager C over ~/top/c with specialist D,
    and a device scope E."""
    top = home.folder("top")
    for sid, name, rel in (
        (A, "mgr", "top"),
        (B, "spec", "top/sub"),
        (C, "sub", "top/c"),
        (D, "deep", "top/c/d"),
        (E, "dev", "e"),
    ):
        home.transcript(sid, home.folder(rel))
        home.staff_file(sid, name, {HERE: f"~/{rel}"})
    c = home.acting(HUMAN, {A: "folder", C: "folder", E: "device"})
    return c, Caller("folder", A, "mgr", 1, folder=top)


def add(owner: str, title: str, **f) -> str:
    return OpenItemAdd(Session(owner), {"title": title, **f}).perform()


def test_ulids_sort_by_time_and_carry_it():
    a, b = items_ops.new_id(1_700_000_000_000), items_ops.new_id(1_700_000_000_001)
    assert len(a) == 26 and a < b and items_ops.made_at(a) == 1_700_000_000.0


def test_a_manager_keeps_its_own_items_and_the_user_anyones(home: Home):
    c, mgr = project(home)
    c._subject = mgr
    ulid = add(A, "write the release notes", held_by="spec", waiting_on="user", where="todo.md")
    raw = yaml.safe_load(items_ops.path(home.config, A).read_text())
    assert raw["items"][0] == {
        "id": ulid,
        "title": "write the release notes",
        "state": "open",
        "waiting_on": "user",
        "held_by": B,
        "where": "todo.md",
    }
    with pytest.raises(Refused, match="may not"):  # another manager's project, even one under it
        add(C, "x")
    with pytest.raises(Refused, match="not a specialist in the project of 'mgr'"):  # D is the sub-manager's
        add(A, "x", held_by="deep")
    c._subject = Caller("unscoped", B, "spec", 1)
    with pytest.raises(Refused, match="may not"):  # a specialist reports instead
        OpenItemDelete(ulid).perform()
    c._subject = HUMAN
    with pytest.raises(Refused, match="a specialist; open items are its manager's"):
        add(B, "x")
    add(C, "the user adds to any manager's")
    OpenItemUpdate(ulid[-6:], {"state": "blocked", "waiting_on": "upstream"}).perform()
    assert OpenItemGet(ulid[-8:]).perform()[1]["state"] == "blocked"
    OpenItemDelete(ulid).perform()
    assert OpenItemsList(A).perform() == []
    assert not items_ops.path(home.config, A).exists()  # no items, no file


def test_list_follows_the_chain_of_command(home: Home):
    c, mgr = project(home)
    mine = add(A, "mine")
    held = add(A, "held by spec", held_by="spec")
    subs = add(C, "the sub-manager's", waiting_on="mgr")
    c._subject = mgr
    assert [i["id"] for _, i in OpenItemsList().perform()] == [mine, held]  # not the sub-manager's
    c._subject = Caller("unscoped", B, "spec", 1)
    assert [i["id"] for _, i in OpenItemsList().perform()] == [held]  # a specialist: what it holds
    c._subject = HUMAN
    with pytest.raises(Refused, match="no project of their own"):
        OpenItemsList().perform()
    assert len(OpenItemsList(everything=True).perform()) == 3
    assert [i["id"] for _, i in OpenItemsList(everything=True, waiting_on="mgr").perform()] == [subs]
    assert [i["id"] for _, i in OpenItemsSearch("SUB-MANAGER", everything=True).perform()] == [subs]


def test_an_item_is_named_by_its_ulid_or_a_unique_ending(home: Home):
    project(home)
    ulid = add(A, "x")
    with pytest.raises(Refused, match="6 or more"):
        OpenItemGet(ulid[-5:]).perform()
    assert OpenItemGet(ulid.lower()[-6:]).perform()[1]["id"] == ulid


def test_reassign_moves_it_within_this_machine(home: Home):
    c, mgr = project(home)
    ulid = add(A, "x")
    c._subject = mgr
    OpenItemReassign(ulid, "spec").perform()  # within the project: held by the specialist
    assert OpenItemsList(A).perform()[0][1]["held_by"] == B
    OpenItemReassign(ulid, "deep").perform()  # to the sub-manager's project, held by its specialist
    assert OpenItemsList(A).perform() == [] and OpenItemsList(C).perform()[0][1]["held_by"] == D
    far = "ffffffff-6666-4666-8666-666666666666"
    home.staff_file(far, "far", {"elsewhere": "~/f"})  # a manager on the other machine
    home.trust(
        f"machines:\n  {HERE}:\n    home: {home.home}\n    machine_id: {portable.machine_id()}\n"
        f"sessions:\n  {A}:\n    scope: folder\n  {C}:\n    scope: folder\n  {far}:\n    scope: folder\n"
    )
    c.refresh()
    c._subject = HUMAN
    with pytest.raises(Refused, match="lives on elsewhere.*delete the item here"):
        OpenItemReassign(ulid, "far").perform()


def test_a_failed_reassign_leaves_both_files(home: Home, monkeypatch: pytest.MonkeyPatch):
    project(home)
    ulid = add(A, "x")
    real = items_ops.write

    def failing(config, sid, items):
        if sid == A:
            raise OSError("disk full")
        return real(config, sid, items)

    monkeypatch.setattr(items_ops, "write", failing)
    with pytest.raises(OSError):
        OpenItemReassign(ulid, "sub").perform()
    monkeypatch.setattr(items_ops, "write", real)
    assert [i["id"] for _, i in OpenItemsList(A).perform()] == [ulid] and OpenItemsList(C).perform() == []


def test_audit_reports_items_no_one_keeps(home: Home):
    c, _ = project(home)
    add(A, "held", held_by="spec")
    add(C, "kept")
    (home.config / "staff.d" / f"{B}.yaml").unlink()  # the specialist leaves
    (home.config / "staff.d" / f"{C}.yaml").unlink()  # and so does the sub-manager
    home.trust(
        f"machines:\n  {HERE}:\n    home: {home.home}\n    machine_id: {portable.machine_id()}\nsessions:\n  {A}:\n    scope: folder\n"
    )
    c.refresh()
    found = {e.subject: e.detail for e in audit.open_items(c.fs, c.model, c.trust)}
    assert any("held_by" in d and B in d for d in found.values())
    assert "not on the staff" in found[C]


def test_an_id_from_before_a_rotate_still_reaches_the_staffer(home: Home):
    c, _ = project(home)
    ulid = add(A, "x", held_by="spec")
    new = "99999999-9999-4999-8999-999999999999"
    f = home.config / "staff.d" / f"{B}.yaml"
    raw = yaml.safe_load(f.read_text())
    raw["history"] = [{"session": B, "rotated": "2026-11-21T14:05:00+08:00", "reason": "conversation gone"}]
    (home.config / "staff.d" / f"{new}.yaml").write_text(yaml.safe_dump(raw))
    f.unlink()
    home.transcript(new, home.folder("top/sub"))
    c.refresh()
    assert c.trust.staffer_now(B).session == new
    c._subject = Caller("unscoped", new, "spec", 1)
    assert [i["id"] for _, i in OpenItemsList().perform()] == [ulid]
    assert StaffHistoryList(new).perform()[0] == {
        "at": "2026-11-21T14:05:00+08:00",
        "event": "rotated",
        "session": B,
        "detail": "conversation gone",
    }


def test_staff_history_add_records_a_rotation_done_by_hand(home: Home):
    c, mgr = project(home)
    old = "88888888-8888-4888-8888-888888888888"
    c._subject = mgr
    st = Context.current().staffer(B)
    with pytest.raises(Refused, match="UTC offset"):
        st.add_history(old, "2026-11-21T14:05:00", "gone").perform()
    with pytest.raises(Refused, match="--reason"):
        st.add_history(old, None, "").perform()
    with pytest.raises(Refused, match="a session of 'mgr' already"):
        st.add_history(A, None, "x").perform()
    st.add_history(old, "2026-11-21T14:05:00+08:00", "conversation gone").perform()
    assert c.trust.staffer_now(old).session == B
    c._subject = Caller("folder", C, "sub", 1, folder=home.home / "top/c")
    with pytest.raises(Refused, match="may not"):  # not its specialist
        Context.current().staffer(B).add_history("77777777-7777-4777-8777-777777777777", None, "x").perform()
