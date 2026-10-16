"""The refusals and undos of `trust machine` and `trust autostart`, and the staff files' dismiss and hire
round trips (ops/staff.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from claudestra.actions.trust_autostart import TrustAutostart
from claudestra.actions.trust_machine import TrustMachine
from claudestra.caller import Refused
from claudestra.context import Context
from claudestra.ops import staff as staff_ops

from conftest import HERE, HUMAN, A, B, Home


def machines(home: Home) -> dict:
    return yaml.safe_load((home.config / "trust.yaml").read_text())["machines"]


def test_trust_machine_refusals(home: Home):
    home.acting(HUMAN)
    with pytest.raises(Refused, match="already under machines"):
        TrustMachine(add=True).perform()
    with pytest.raises(Refused, match="is not under machines"):
        TrustMachine(add=False, host="nowhere").perform()
    TrustMachine(add=False).perform()
    with pytest.raises(Refused, match="leave --machine-id out"):
        TrustMachine(add=True, machine_id="wrong").perform()


def test_trust_machine_remove_and_undo(home: Home):
    home.acting(HUMAN)
    TrustMachine(add=True, host="far", home=Path("/home/far"), machine_id="abc").perform()
    assert "ssh" not in machines(home)["far"]
    remove = TrustMachine(add=False, host="FAR")  # hostnames match in any case
    assert remove.describe() == ["trust.yaml: FAR is no longer described"]
    remove.perform()
    assert "far" not in machines(home)
    remove.undo()
    assert machines(home)["far"]["machine_id"] == "abc"
    assert Context.current().trust.machines["far"].home == Path("/home/far")


def test_trust_machine_add_describes_this_machine_with_its_own_id(home: Home):
    home.acting(HUMAN)
    TrustMachine(add=False).perform()  # the last machine: what is left is the header alone
    assert yaml.safe_load((home.config / "trust.yaml").read_text()) is None
    add = TrustMachine(add=True, ssh="u@here")
    add.perform()
    assert machines(home)[HERE]["ssh"] == "u@here" and machines(home)[HERE]["home"] == str(home.home)
    add.undo()
    assert yaml.safe_load((home.config / "trust.yaml").read_text()) is None


def test_trust_autostart_refusals_and_undo(home: Home):
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    home.staff_file(B, "far", {"elsewhere": "~/w"})
    home.acting(HUMAN)
    with pytest.raises(Refused, match="is not under machines"):
        TrustAutostart(A, True, host="nowhere").perform()
    with pytest.raises(Refused, match="not a staffer with a folder on"):
        TrustAutostart(B, True).perform()
    with pytest.raises(Refused, match="does not start at login"):
        TrustAutostart(A, False).perform()
    add = TrustAutostart(A, True)
    assert add.describe() == [f"trust.yaml: {A} (one) starts at login on {HERE}"]
    add.perform()
    with pytest.raises(Refused, match="already starts at login"):
        TrustAutostart(A, True).perform()
    remove = TrustAutostart(A, False)
    remove.perform()
    assert "autostart" not in machines(home)[HERE]  # an empty list is left out
    remove.undo()
    assert Context.current().trust.autostart(HERE) == [A]


def test_staff_files_dismiss_hire_and_undo_round_trip(home: Home):
    config = home.config
    original = home.staff_file(A, "one", {HERE: "~/w"}).read_text()
    assert staff_ops.dismissed(config, A) is None and staff_ops.dismiss(config, A) is None
    assert staff_ops.dismissed(config, A)["name"] == "one"
    staff_ops.undismiss(config, A)
    assert staff_ops.staff_path(config, A).read_text() == original
    older = staff_ops.dismiss(config, A)
    staff_ops.hire(config, A, "two", {HERE: "~/w"}, "again")
    assert not staff_ops.dismissed_path(config, A).exists()
    with pytest.raises(Refused, match="exists already"):
        staff_ops.hire(config, A, "two", {HERE: "~/w"}, "again")
    staff_ops.unhire(config, A, original)  # the dismissed copy it replaced comes back
    assert staff_ops.dismissed_path(config, A).read_text() == original and older is None
    # A second dismissal keeps the older dismissed copy for its undo.
    staff_ops.hire(config, A, "three", {HERE: "~/w"}, "x")
    staff_ops.dismissed_path(config, A).write_text(original)
    older = staff_ops.dismiss(config, A)
    assert older == original and "three" in staff_ops.dismissed_path(config, A).read_text()
    staff_ops.undismiss(config, A, older)
    assert "three" in staff_ops.staff_path(config, A).read_text()
    assert staff_ops.dismissed_path(config, A).read_text() == original


def test_a_dismissed_file_that_is_not_a_mapping_is_refused(home: Home):
    p = staff_ops.dismissed_path(home.config, A)
    p.parent.mkdir(parents=True)
    p.write_text("- a list\n")
    with pytest.raises(Refused, match="not a mapping"):
        staff_ops.dismissed(home.config, A)
