"""DESIGN.md's permission tables (§6.1) say what the actions declare: a change to who may do what is
a change to both, or this fails."""

from __future__ import annotations

from pathlib import Path

from claudestra.actions import permissions as perm

DESIGN = Path(__file__).resolve().parents[1] / "DESIGN.md"
COLUMNS = {
    "User": perm.USER,
    "Manager": perm.MANAGER,
    "D: manager": perm.D_MANAGER,
    "D: unmanaged": perm.D_UNMANAGED,
    "D: managed": perm.D_MANAGED,
    "D: device": perm.D_DEVICE,
    "D: off staff": perm.D_OTHER,
    "Login": perm.LOGIN_AUTOSTART,
}
KINDS = {"the user": {"human"}, "the user, or a device scope": {"human", "device"}}


def _table(after: str) -> list[list[str]]:
    """The rows of the first table after the line `after`, header and rule dropped."""
    lines = DESIGN.read_text().splitlines()
    rows, start = [], lines.index(after) + 1
    for line in lines[start:]:
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif rows:
            break
    return rows


def test_the_tables_match_what_each_action_declares():
    rules = perm.matrix()
    on_session = _table("**Actions on a session:**")
    header, body = on_session[0][1:], on_session[2:]
    written = {}
    for row in body:
        allowed = {COLUMNS[h] for h, cell in zip(header, row[1:], strict=True) if cell == "yes"}
        if row[0] in ("fix-name", "describe"):
            allowed.add(perm.SELF)  # "also allow the staffer itself"
        written[row[0]] = allowed
    for row in _table("**Actions on anything else:**")[2:]:
        for verb in row[0].split(", "):
            written[verb] = KINDS[row[1]]
    declared = {
        v: set(getattr(r, "allowed", None) or getattr(r, "kinds", set()))
        for v, r in rules.items()
        if not isinstance(r, perm.Anyone)
    }
    assert written == declared
