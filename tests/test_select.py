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
        offered[message] = [c.value for c in choices]
        return Answer(choices[0].value)

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
    monkeypatch.setattr(
        select.questionary, "checkbox", lambda message, choices, **kw: Answer([c.value for c in choices])
    )
    assert sorted(s.id for s in select.Sessions(many=True).get(None)) == [A, B]
