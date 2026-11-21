"""Open items, on the files: `open-items.d/<manager's session ID>.yaml` in the config folder, one file per
manager, written by claudestra on the machine the manager lives on and nowhere else, so that a synced config
folder never has two machines writing one file (DESIGN.md §6.7). Who may change them is the actions' to
decide (actions/open_items_*.py).

An item is the summary of a piece of open work in a manager's project: a ULID, a title, a short description,
its state, what it waits on, the specialist holding it, and where the project tracks it in detail. A finished
item is deleted, by its manager once it has checked the work is done; claudestra's log keeps the history.
Session IDs written in an item (`held_by`, `waiting_on`) are read through the staff's history, so one written
before a `staff rotate` still reaches the staffer.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import yaml

from ..caller import Refused
from ..claude_fs import UUID
from ..portable import atomic_write_text
from ..trust import StaffFile, Trust

DIR = "open-items.d"
STATES = ("open", "waiting", "blocked")
WAITS = ("user", "upstream")  # or a staffer, by session ID
FIELDS = ("id", "title", "description", "state", "waiting_on", "held_by", "where")
HEADER = "# Written by `claudestra open-items`; change it with that command.\n"
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
SHORT = 8  # the characters of a ULID a table shows: its last, since its first are the time it was made
MIN_TOKEN = 6  # the fewest characters of a ULID's end that name an item


def new_id(now_ms: int | None = None) -> str:
    """A ULID: 48 bits of milliseconds since the epoch, then 80 random bits, in Crockford's base 32."""
    n = ((now_ms if now_ms is not None else time.time_ns() // 1_000_000) << 80) | int.from_bytes(os.urandom(10))
    return "".join(CROCKFORD[(n >> (5 * i)) & 31] for i in reversed(range(26)))


def made_at(ulid: str) -> float:
    """When an item was made, in seconds since the epoch, from its ULID."""
    ms = 0
    for ch in ulid[:10]:
        ms = ms * 32 + CROCKFORD.index(ch)
    return ms / 1000


def path(config: Path, sid: str) -> Path:
    return config / DIR / f"{sid}.yaml"


def read(config: Path, sid: str) -> list[dict]:
    p = path(config, sid)
    if not p.is_file():
        return []
    raw = yaml.safe_load(p.read_text()) or {}
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not all(isinstance(i, dict) and isinstance(i.get("id"), str) for i in items):
        raise Refused(f"{p} is not a list of items under `items`; fix it by hand first")
    return items


def every(config: Path) -> dict[str, list[dict]]:
    """Every manager's items, by the session ID its file is named by."""
    d = config / DIR
    files = sorted(f for f in d.glob("*.yaml") if UUID.match(f.stem)) if d.is_dir() else []
    return {f.stem: read(config, f.stem) for f in files}


def write(config: Path, sid: str, items: list[dict]) -> str | None:
    """Write a manager's items, oldest first, leaving out empty fields; no items, no file. Returns the text
    before, for `restore` (None if there was no file)."""
    p = path(config, sid)
    before = p.read_text() if p.is_file() else None
    if not items:
        if before is not None:
            p.unlink()
        return before
    tidy = [{k: i[k] for k in FIELDS if i.get(k) not in (None, "")} for i in sorted(items, key=lambda i: i["id"])]
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(p, HEADER + yaml.safe_dump({"items": tidy}, sort_keys=False, allow_unicode=True, width=100))
    return before


def restore(config: Path, sid: str, before: str | None) -> None:
    p = path(config, sid)
    if before is None:
        if p.exists():
            p.unlink()
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(p, before)


def find(config: Path, token: str) -> tuple[str, dict]:
    """The item a ULID, or a unique ending of it of MIN_TOKEN or more characters, names, with its owner."""
    t = token.strip().upper()
    if len(t) < MIN_TOKEN:
        raise Refused(f"give an item's ULID, or the last {MIN_TOKEN} or more characters of it")
    hits = [(sid, i) for sid, items in every(config).items() for i in items if i["id"].endswith(t)]
    if not hits:
        raise Refused(f"no open item's ULID ends {t}")
    if len(hits) > 1:
        raise Refused(f"{t} ends {len(hits)} items' ULIDs: {', '.join(i['id'] for _, i in hits)}")
    return hits[0]


def follow(config: Path, old: str, new: str) -> None:
    """A rotated manager's items go with it: its file is renamed to the new session's ID (and back, for an undo).
    A rotate runs on the machine the manager lives on, which is the one that writes the file."""
    if (p := path(config, old)).exists():
        dst = path(config, new)
        if dst.exists():
            raise Refused(f"{dst} exists already")
        p.rename(dst)


def owner_problem(trust: Trust, sessions, sid: str) -> str | None:
    """Why the session cannot hold open items written here, if it cannot: only a manager holds them (a folder
    or device scope), and its file is written only on the machine it lives on."""
    sf = trust.staff_file(sid)
    if sf is None:
        return f"{sid} is not on the staff"
    if trust.scope(sid) is None:
        return f"{sf.name!r} is a specialist; open items are its manager's to hold"
    if sid not in sessions:
        others = [str(h) for h in sf.folders]
        return f"{sf.name!r} lives on {' or '.join(others) or 'no machine'}, not here; change its open items there"
    return None


# --- the projects items belong to -------------------------------------------------------------------


def manager_of(trust: Trust, sf: StaffFile) -> StaffFile | None:
    """The manager whose project a specialist's work is: its nearest folder manager on this machine, or with
    none, this machine's device scope. A sub-manager's project is its own, so the nearest is the one."""
    if over := trust.managers_over(sf):
        return max(over, key=lambda m: len(m.folder.parts))
    return next((d for d in trust.device_managers() if d.session != sf.session), None)


def in_project(trust: Trust, owner: str, sid: str) -> bool:
    """Whether the staffer `sid` is a specialist in manager `owner`'s project, here."""
    sf = trust.staffer_now(sid)
    if sf is None or trust.scope(sf.session) is not None or sf.folder is None:
        return False
    m = manager_of(trust, sf)
    return m is not None and m.session == owner


def resolve_wait(trust: Trust, value: str | None) -> str | None:
    """`waiting_on` as written: user, upstream, a staffer's session ID (given by name or ID), or none."""
    if value in (None, "", "none", "-"):
        return None
    if value in WAITS:
        return value
    sf = trust.named(value) or trust.staffer_now(value)
    if sf is None:
        raise Refused(f"waiting on {value!r}: give user, upstream, none, or a staffer's name")
    return sf.session
