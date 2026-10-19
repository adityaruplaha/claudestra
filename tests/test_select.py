"""The selectors: a value given is used as given; at a terminal one is picked from a list narrowed by what the
command allows; off a terminal the command refuses and names what to give; and shell completion offers the
same values the picker would."""

from __future__ import annotations

import pytest
import typer

from claudestra.cli import select

from conftest import HERE, HUMAN, A, B, C, Home


class Answer:
    def __init__(self, value):
        self.value = value

    def ask(self):
        return self.value


def test_off_a_terminal_it_names_what_to_give(home: Home, capsys):
    home.acting(HUMAN)
    for chooser, what in (
        (select.Sessions(), "a session"),
        (select.Staffers(), "a staffer"),
        (select.TrashEntries(), "a trash entry"),
        (select.Folder(), "the folder"),
        (select.OneOf({"a": ""}, "a scope", "?"), "a scope"),
        (select.Sessions(many=True), "a session"),
    ):
        with pytest.raises(typer.Exit):
            chooser.get(None)
        assert f"give {what}" in capsys.readouterr().err


def test_a_value_given_is_used_and_a_bad_choice_refused(home: Home):
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    home.acting(HUMAN)
    assert select.Sessions().get(A).id == A
    assert [s.id for s in select.Sessions(many=True).get([A])] == [A]
    assert select.Staffers().get("one") == A
    assert select.OneOf({"device": "", "folder": ""}, "a scope", "?").get("folder") == "folder"
    with pytest.raises(typer.Exit):
        select.OneOf({"device": ""}, "a scope", "?").get("nope")


def test_the_list_is_narrowed_and_completion_agrees(home: Home, at_terminal, monkeypatch):
    for sid in (A, B, C):
        home.transcript(sid, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    home.staff_file(B, "two", {"elsewhere": "~/w"})
    home.acting(HUMAN, {A: "folder"})
    offered = {}

    def choose(message, choices, **kw):
        offered[message] = values(choices)
        return Answer(offered[message][0])

    monkeypatch.setattr(select.questionary, "select", choose)
    off_staff = select.Sessions(staff=False, message="off staff")
    off_staff.get()
    assert offered["off staff"] == [C] == [v for v, _ in off_staff.complete("")]
    select.Staffers(here=True, message="here").get()
    assert offered["here"] == [A]
    select.Staffers().where(on="elsewhere", message="there").get()
    assert offered["there"] == [B]
    select.Staffers(scoped=True, message="scoped").get()
    assert offered["scoped"] == [A]
    assert [v for v, _ in select.Staffers(scoped=True).complete("")] == ["one"]  # completed by name


def test_several_are_ticked_from_one_list(home: Home, at_terminal, monkeypatch):
    for sid in (A, B):
        home.transcript(sid, home.folder("w"))
    home.acting(HUMAN)
    monkeypatch.setattr(select.questionary, "checkbox", lambda message, choices, **kw: Answer(values(choices)))
    assert sorted(s.id for s in select.Sessions(many=True).get(None)) == [A, B]


def values(choices) -> list:
    """What a picker offers."""
    return [c.value for c in choices]


def test_a_picker_is_a_coloured_table_that_filters(home: Home, at_terminal, monkeypatch):
    """A header above the rows, which is not a row, rows in aligned columns, coloured as the lists are, and
    filtered by their text."""
    home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    home.staff_file(B, "a-longer-name", {"elsewhere": "~/w"})
    home.acting(HUMAN, {A: "device"})
    shown = {}

    def choose(message, choices, **kw):
        shown["choices"], shown["instruction"] = choices, kw["instruction"]
        return Answer(values(choices)[0])

    monkeypatch.setattr(select.questionary, "select", choose)
    select.Staffers().get()
    rows = shown["choices"]
    assert not any(isinstance(r, select.questionary.Separator) for r in rows)  # the pointer lands on a row as one types
    header = shown["instruction"].split("\n")[1]
    assert header.lstrip().startswith("name")
    texts = ["   " + "".join(t for _, t in r.title) for r in rows]  # as shown, past the pointer
    assert texts[0].index(B[:8]) == texts[1].index(A[:8]) == header.index("session")
    assert "one" in rows[1].title.lower() and "elsewhere" in rows[0].title.lower()
    styles = {t.strip(): st for r in rows for st, t in r.title}
    assert "ansicyan" in styles[A[:8]] and "magenta" in styles["device"] and "bold" in styles["one"]


def test_a_staffer_that_lives_elsewhere_is_named_by_its_id_prefix(home: Home):
    home.staff_file(B, "far", {"elsewhere": "~/w"})
    home.acting(HUMAN)
    assert select.Staffers().get(B[:8]) == B
    with pytest.raises(typer.Exit):
        select.Staffers().get(B[:7])  # shorter than a prefix may be
