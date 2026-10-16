"""Update reminders (DESIGN.md §6.6): at the user's terminal, at most once a day, claudestra asks the
repository it was installed from for the newest release tag, and says so when it is newer than the one
running. It asks the remote uv recorded at install (`uv-receipt.toml` in its own environment), over
whatever that remote uses, ssh included, and never prompts for a password; an install from a checkout
has no remote to ask, and is a developer's, updated by pulling, so it is never reminded. The user turns
it off with `claudestra preferences update-reminders no`. The remote is asked in a process of its own, so
no command waits on the network; a check that fails says nothing and is not tried again that day.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

REPO = "https://github.com/adityaruplaha/claudestra"  # where the plugin installs from by default
DAY = 24 * 3600
TAG = re.compile(r"refs/tags/v(\d+)\.(\d+)\.(\d+)$")


def _cache(home: Path) -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache") / "claudestra" / "latest.json"


def _version(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def source(prefix: Path | None = None) -> str | None:
    """The git remote claudestra was installed from, as uv recorded it; None for a checkout or an unknown install."""
    try:
        receipt = tomllib.loads(((prefix or Path(sys.prefix)) / "uv-receipt.toml").read_text())
        url = next(r["git"] for r in receipt["tool"]["requirements"] if r.get("name") == "claudestra" and "git" in r)
    except (OSError, ValueError, KeyError, StopIteration):
        return None
    url = url.removeprefix("git+").split("?")[0].split("#")[0]
    return re.sub(r"(\.git)?@[^/@]+$", r"\1", url) if "://" in url else url


def latest(timeout: float = 5) -> str | None:
    """The newest release tag where claudestra was installed from, or None if it cannot be asked."""
    remote = source()
    if remote is None:
        return None
    try:
        r = subprocess.run(
            ["git", "ls-remote", "--tags", "--refs", remote],
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": "ssh -o BatchMode=yes"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    tags = [m.groups() for line in r.stdout.splitlines() if (m := TAG.search(line))]
    return ".".join(max(tags, key=lambda t: tuple(map(int, t)))) if r.returncode == 0 and tags else None


def refresh(home: Path, now: float, ask=latest) -> dict:
    """Ask the remote now, and remember the answer and when."""
    seen = {"checked": now, "latest": ask()}
    cache = _cache(home)
    with contextlib.suppress(OSError):
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(seen))
    return seen


def refresh_later(home: Path) -> None:
    """Ask the remote in a process of its own, so no command waits on the network; the next one reads it."""
    with contextlib.suppress(OSError):
        subprocess.Popen(
            [sys.executable, "-I", "-m", "claudestra.ops.updates", str(home)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )


def reminder(home: Path, running: str, now: float | None = None, ask=None) -> str | None:
    """What to tell the user, if a newer release is out; asks the repository at most once a day. Nothing for an
    editable install or one from a local folder: that is a developer's, updated by pulling."""
    if source() is None:
        return None
    now = time.time() if now is None else now
    cache = _cache(home)
    try:
        seen = json.loads(cache.read_text())
    except (OSError, ValueError):
        seen = {}
    if not isinstance(seen, dict) or "checked" not in seen or now - float(seen["checked"]) > DAY:
        if ask is None:  # in the background; this command says what was known before
            refresh_later(home)
        else:
            seen = refresh(home, now, ask)
    new = seen.get("latest")
    if isinstance(new, str) and _version(new) > _version(running):
        return (
            f"claudestra {new} is out; this is {running}. Update the claudestra plugin, or run "
            f"`uv tool install --force git+{source() or REPO}@v{new}`. "
            "(`claudestra preferences update-reminders no` stops these.)"
        )
    return None


if __name__ == "__main__":
    refresh(Path(sys.argv[1]), time.time())
