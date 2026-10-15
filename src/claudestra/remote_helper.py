"""Run on the other machine by `claudestra send` and `claudestra fetch`, as `python3 - <json>`.

The script is portable.py's source followed by this file's, so the far side runs the same code for
every shared job; it needs neither claudestra nor the same ~/.claude checkout there. It reads and reports,
except for `trash` (moving a sent session's stores to that machine's trash) and `log`. Prints one
JSON object.
"""

import contextlib
import json
import os
import socket
import sys
from pathlib import Path

with contextlib.suppress(ImportError):  # imported in the package; shipped, these are defined above
    from .portable import (
        filed_slug,
        log_line,
        machine_id,
        running_pid,
        sha256,
        state_dir,
        trash_into,
    )

HOME = Path(os.environ.get("CAM_REMOTE_HOME") or Path.home())
ROOT = HOME / ".claude"
PROJECTS = ROOT / "projects"
PROC = Path("/proc")


def safe(rel: str) -> Path:
    """A path inside ~/.claude and outside any memory folder, never following a symlink at its end."""
    p = ROOT / rel
    if not (p.parent.resolve() / p.name).is_relative_to(ROOT.resolve()) or "memory" in Path(rel).parts:
        raise SystemExit(json.dumps({"error": f"refusing {rel}"}))
    return p


def probe(args: dict) -> dict:
    sid = args["sid"]
    found = [*sorted(PROJECTS.glob(f"*/{sid}.jsonl")), *sorted(PROJECTS.glob(f"*/{sid}"))]
    found += [
        *sorted(PROJECTS.glob(f"*/{sid}.orphaned-*.jsonl")),
        *sorted(PROJECTS.glob(f"*/{sid}.jsonl.superseded-*")),
    ]
    stores = [str(p.relative_to(ROOT)) for p in found]
    for store in args.get("keyed", []):
        for key in [sid, *args.get("secondary", [])]:
            if (ROOT / store / key).exists():
                stores.append(f"{store}/{key}")
    return {
        "hostname": socket.gethostname(),
        "machine_id": machine_id(),
        "home": str(HOME),
        "running": running_pid(ROOT / "sessions", PROC, sid),
        "stores": stores,
        "dirs": {d: os.path.isdir(d) for d in args.get("dirs", [])},
        "filed": {f: filed_slug(PROJECTS, f) for f in args.get("filed", [])},
    }


def sha(args: dict) -> dict:
    return {rel: (sha256(p) if (p := safe(rel)).is_file() and not p.is_symlink() else None) for rel in args["files"]}


def list_files(args: dict) -> dict:
    files, links = [], []
    for rel in args["stores"]:
        p = safe(rel)
        for f in [p] if p.is_symlink() or not p.is_dir() else sorted(p.rglob("*")):
            if f.is_symlink():
                links.append(str(f.relative_to(ROOT)))
            elif f.is_file():
                files.append(str(f.relative_to(ROOT)))
    return {"files": files, "links": links}


def trash(args: dict) -> dict:
    sid = args["sid"]
    if running_pid(ROOT / "sessions", PROC, sid):
        raise SystemExit(json.dumps({"error": f"{sid} is running here"}))
    items = [(rel, safe(rel)) for rel in args["stores"] if (ROOT / rel).exists() or (ROOT / rel).is_symlink()]
    return {"entry": trash_into(ROOT, sid, items, args.get("slug"), args.get("title"), args.get("reason")).name}


def log(args: dict) -> dict:
    log_line(state_dir(HOME), args["entry"])
    return {}


ACTIONS = {"probe": probe, "sha": sha, "list": list_files, "trash": trash, "log": log}

if __name__ == "__main__":
    print(json.dumps(ACTIONS[json.loads(sys.argv[1])["action"]](json.loads(sys.argv[1]))))
