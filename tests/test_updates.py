"""Update reminders: a newer tag is said, at most one question to the repository a day, and nothing on failure."""

from __future__ import annotations

from pathlib import Path

from claudestra.ops import updates


def test_a_newer_release_is_said_and_the_repository_asked_once_a_day(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(updates, "source", lambda: "ssh://git@github.com/o/claudestra.git")
    asked = []

    def ask():
        asked.append(1)
        return "0.3.0"

    assert "0.3.0 is out" in updates.reminder(tmp_path, "0.2.0", now=1000.0, ask=ask)
    assert "0.3.0 is out" in updates.reminder(tmp_path, "0.2.0", now=1000.0 + 3600, ask=ask)
    assert len(asked) == 1
    assert updates.reminder(tmp_path, "0.3.0", now=1000.0 + 2 * updates.DAY, ask=ask) is None
    assert len(asked) == 2


def test_a_failed_check_says_nothing_and_a_checkout_is_never_checked(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(updates, "source", lambda: None)  # editable, or from a local folder
    assert updates.reminder(tmp_path, "0.2.0", now=1.0, ask=lambda: "9.9.9") is None
    monkeypatch.setattr(updates, "source", lambda: "ssh://git@github.com/o/claudestra.git")
    assert updates.reminder(tmp_path, "0.2.0", now=1.0, ask=lambda: None) is None


def test_versions_compare_as_numbers():
    assert updates._version("0.10.0") > updates._version("0.9.9")


def test_the_source_is_the_remote_uv_recorded(tmp_path: Path):
    def receipt(req: str) -> Path:
        (tmp_path / "uv-receipt.toml").write_text(f"[tool]\nrequirements = [{req}]\n")
        return tmp_path

    assert updates.source(receipt('{ name = "claudestra", editable = "/src/claudestra" }')) is None
    got = updates.source(receipt('{ name = "claudestra", git = "ssh://git@github.com/o/claudestra.git?tag=v0.1.1" }'))
    assert got == "ssh://git@github.com/o/claudestra.git"
    got = updates.source(receipt('{ name = "claudestra", git = "git+ssh://git@github.com/o/claudestra.git@v0.1.1" }'))
    assert got == "ssh://git@github.com/o/claudestra.git"
