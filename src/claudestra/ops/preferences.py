"""The user's preferences (DESIGN.md §6.6): `preferences.yaml` in the config folder, kept in step between
machines with the rest of it. `claudestra setup` asks each one; sessions read them with `claudestra
preferences`, since the config folder is closed to them. "ask" leaves the choice to the user each time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ..caller import Refused
from ..portable import atomic_write_text

FILE = "preferences.yaml"


@dataclass(frozen=True)
class Preference:
    question: str
    choices: dict[str, str]  # value -> what it means, for the question and for sessions reading it
    unset: str = "ask the user"  # what holds until the user chooses


PREFERENCES: dict[str, Preference] = {
    "finished-transcripts": Preference(
        "Once a session's work has gone out (a report handed in, a change merged), what happens to its conversation?",
        {
            "ask": "ask the user whether to keep it",
            "keep": "keep it; propose removing a session only when the user asks",
            "disposable": "it has served its purpose: offer to trash it without raising the loss of its history",
        },
    ),
    "fan-out-model": Preference(
        "When a session runs many subagents on one job, which model do they use?",
        {
            "ask": "project the usage and ask the user before launching anything large",
            "same": "the session's own model, whatever the size",
            "cheaper": "a cheaper model for a heavy fan-out, the session's own for a light one; "
            "say the projection and the choice before launching anything large",
        },
    ),
    "update-reminders": Preference(
        "Should claudestra remind you, at your terminal, when a newer release is out?",
        {"yes": "check at most once a day, and say so when a newer release is out", "no": "never check"},
        unset="yes",
    ),
}


def path(config: Path) -> Path:
    return config / FILE


def load(config: Path) -> dict[str, str | None]:
    """Each preference's value, or None where the user has not chosen yet."""
    p = path(config)
    try:
        raw = yaml.safe_load(p.read_text()) if p.is_file() else {}
    except (OSError, yaml.YAMLError) as e:
        raise Refused(f"cannot read {p}: {e}") from e
    raw = raw if isinstance(raw, dict) else {}
    return {
        k: (v if isinstance(v := raw.get(k), str) and v in pref.choices else None) for k, pref in PREFERENCES.items()
    }


def check(key: str, value: str) -> None:
    if key not in PREFERENCES:
        raise Refused(f"no preference {key!r}; there are {', '.join(PREFERENCES)}")
    if value not in PREFERENCES[key].choices:
        raise Refused(f"{key} is one of {', '.join(PREFERENCES[key].choices)}, not {value!r}")


def save(config: Path, key: str, value: str) -> None:
    check(key, value)
    have = {k: v for k, v in load(config).items() if v is not None}
    have[key] = value
    header = "# The user's preferences for claudestra; written by `claudestra setup` and `claudestra preferences`.\n"
    atomic_write_text(path(config), header + yaml.safe_dump(have, sort_keys=False))
