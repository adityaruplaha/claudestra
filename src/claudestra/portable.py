"""The jobs claudestra does on both machines, each stated once, in the standard library only.

claudestra imports this module, and `claudestra machine send` and `claudestra machine fetch` ship its source, followed by
remote_helper.py's, to the other machine as one script, so that side runs this same code rather than a
copy of it. Nothing here may import from the rest of the package.
"""

import datetime as _dt
import hashlib
import hmac
import json
import os
import re
import shutil
from pathlib import Path

# claudestra's app ID, fixed once: the message in its machine IDs. Changing it changes every
# machine_id in trust.yaml.
APP_ID = "087e99007e6f4d4fb75a0ae2c49f9ae5"
TRASH = "session-trash"  # under ~/.claude; each entry is <stamp>-<session ID>/ with stores/ and MANIFEST
STATE = "claudestra"  # claudestra's log and lock, under $XDG_STATE_HOME
ALIASES = ".session-aliases"  # a multi-root workspace's redirect, in a slug folder


def slug(folder) -> str:
    """The name Claude Code files a folder's sessions under in ~/.claude/projects/.

    Lossy: every character other than an ASCII letter or digit becomes '-', so 'a b', 'a.b',
    'a-b' and 'a/b' all map to the same slug, and a slug cannot be turned back into a folder.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", str(folder))


def given_folder(p) -> Path:
    """A folder as a person or a session gave it: ~ expanded, made absolute and normalised, so that a `..` in
    it cannot leave it looking inside a folder it is not in (a permission is a test of `is_relative_to`)."""
    return Path(os.path.normpath(Path(p).expanduser().absolute()))


LONG_SLUG = 200  # past this, Claude Code truncates a slug and appends a hash of the path (DESIGN.md §3)


def slug_problem(folder):
    """Why claudestra cannot tell where sessions started in `folder` are filed, if it cannot."""
    if len(s := slug(os.path.normpath(str(folder)))) > LONG_SLUG:
        return f"{folder}'s slug is {len(s)} characters; Claude Code shortens such slugs with a hash claudestra cannot reproduce"
    return None


def filed_slug(projects: Path, folder) -> str:
    """The slug Claude Code files sessions started in `folder` under: its own, or, when that slug
    holds a `.session-aliases` redirect (a multi-root workspace's other folder), the one it names."""
    own = slug(os.path.normpath(str(folder)))
    try:
        target = Path((projects / own / ALIASES).read_text().strip())
    except OSError:
        return own
    return target.name if target.parent == projects and target.name else own


def proc_stat(proc: Path, pid: int):
    """(parent pid, start time) from /proc/<pid>/stat, or None if the process is gone.

    The start time is field 22, which Claude Code records in a session file as procStart.
    """
    try:
        data = (proc / str(pid) / "stat").read_text()
    except OSError:
        return None
    rest = data[data.rindex(")") + 2 :].split()  # the command name may hold spaces and ')'
    return int(rest[1]), rest[19]  # fields 4 and 22


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def live_pid_record(sessions: Path, proc: Path, pid: int):
    """The session file of process `pid`, if that process still runs with the start time it records."""
    rec = read_json(sessions / f"{pid}.json")
    st = proc_stat(proc, pid)
    if (
        isinstance(rec, dict)
        and st is not None
        and str(rec.get("procStart")) == st[1]
        and isinstance(rec.get("sessionId"), str)
    ):
        return rec
    return None


def running_pid(sessions: Path, proc: Path, session_id: str):
    """The pid of a live run of the session on this machine, or None."""
    for f in sessions.glob("*.json") if sessions.is_dir() else []:
        if (
            f.stem.isdigit()
            and (rec := live_pid_record(sessions, proc, int(f.stem)))
            and rec["sessionId"] == session_id
        ):
            return int(f.stem)
    return None


def app_machine_id(raw: str, app_id: str = APP_ID) -> str:
    """sd_id128_get_machine_app_specific(): HMAC-SHA256 keyed by the machine ID over the app ID,
    cut to 128 bits and marked as a v4 UUID. The raw ID cannot be recovered from it, so it may
    leave the machine; the raw one may not (machine-id(5)). Same as
    `systemd-id128 machine-id --app-specific=<app ID>`."""
    b = bytearray(hmac.new(bytes.fromhex(raw), bytes.fromhex(app_id), hashlib.sha256).digest()[:16])
    b[6] = (b[6] & 0x0F) | 0x40
    b[8] = (b[8] & 0x3F) | 0x80
    return b.hex()


def machine_id(app_id: str = APP_ID):
    """This machine's derived ID, or None where /etc/machine-id cannot be read."""
    try:
        raw = Path("/etc/machine-id").read_text().strip()
        return app_machine_id(raw, app_id) if raw else None
    except (OSError, ValueError):
        return None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stamp() -> str:
    """A UTC timestamp for names: trash entries, backups, staging folders."""
    return _dt.datetime.now(_dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def atomic_write_text(path: Path, text: str, mode=None, errors: str = "strict") -> None:
    """Write beside the file and move into place, keeping its mode (or setting `mode`).

    `errors="surrogateescape"` writes back bytes that were read the same way, unchanged.
    """
    keep = mode if mode is not None else (path.stat().st_mode & 0o777 if path.exists() else None)
    tmp = path.with_name(path.name + ".claudestra-tmp")
    tmp.write_text(text, encoding="utf-8", errors=errors)
    if keep is not None:
        os.chmod(tmp, keep)
    os.replace(tmp, path)


def move_into(src: Path, dst: Path) -> None:
    """Move without overwriting: a destination that exists is an error."""
    if dst.exists() or dst.is_symlink():
        raise FileExistsError(f"{dst} already exists")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))


MANIFEST = "manifest.json"  # in each trash entry: {session_id, slug, title, removed_at, moves: [{from, to}], reason?}


def read_manifest(entry: Path):
    raw = read_json(entry / MANIFEST)
    return raw if isinstance(raw, dict) else None


def write_manifest(entry: Path, manifest: dict) -> None:
    atomic_write_text(entry / MANIFEST, json.dumps(manifest, indent=2))


def trash_into(root: Path, session_id: str, items, slug_name=None, title=None, reason=None) -> Path:
    """Move a session's stores into a new trash entry: <root>/session-trash/<stamp>-<id>/stores/<label>,
    with a manifest.json listing every move. The manifest is written even when a move fails part way,
    so what did move can be restored. `items` is (label, path) pairs."""
    entry = root / TRASH / f"{stamp()}-{session_id}"
    entry.mkdir(parents=True)
    moves = []
    try:
        for label, src in items:
            dst = entry / "stores" / label
            move_into(src, dst)
            moves.append({"from": str(src), "to": str(dst)})
    finally:
        manifest = {
            "session_id": session_id,
            "slug": slug_name,
            "title": title,
            "removed_at": _dt.datetime.now(_dt.UTC).isoformat(),
            "moves": moves,
        }
        if reason:
            manifest["reason"] = reason
        write_manifest(entry, manifest)
    return entry


def state_dir(home: Path) -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", home / ".local" / "state")) / STATE


def log_line(state: Path, entry: dict) -> None:
    """Append one JSON line to claudestra's log."""
    state.mkdir(parents=True, exist_ok=True)
    with open(state / "log", "a") as f:
        f.write(json.dumps(entry) + "\n")


def now_local() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")
