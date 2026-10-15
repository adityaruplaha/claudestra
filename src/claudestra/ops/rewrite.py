"""Rewriting a moved session's working directories, as if it had always run there.

The rule is in DESIGN.md §9. Only `cwd` fields change. Transcripts can hold invalid UTF-8 and lone
surrogates (cut tool output), so lines are read and written with surrogateescape, and a rewritten record
is dumped with ASCII escapes, which cannot fail; every other line is written back byte for byte.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from ..portable import atomic_write_text

LOSSLESS = "surrogateescape"


def mapper(
    pairs: list[tuple[str, str]], exists: Callable[[str], bool] = os.path.isdir, exact: bool = False
) -> Callable[[str], str | None]:
    """OLD becomes NEW, and OLD/x becomes NEW/x where that exists (on the destination), else NEW.

    The longest matching OLD wins. `exists` answers for the destination machine, which for a
    transfer is not this one. With `exact`, only OLD itself is rewritten and OLD/x is left alone:
    for a session launched in OLD that also did real work in OLD's subfolders.
    """
    pairs = sorted(((o.rstrip("/"), n.rstrip("/")) for o, n in pairs), key=lambda p: -len(p[0]))

    def mapped(cwd: str) -> str | None:
        for old, new in pairs:
            if cwd == old:
                return new
            if not exact and cwd.startswith(old + "/"):
                candidate = new + cwd[len(old) :]
                return candidate if exists(candidate) else new
        return None

    return mapped


def _lines(path: Path, mapped: Callable[[str], str | None]) -> tuple[list[str], dict[str, int]]:
    out, changed = [], {}
    with path.open(encoding="utf-8", errors=LOSSLESS, newline="") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except ValueError:
                rec = None
            cwd = rec.get("cwd") if isinstance(rec, dict) else None
            new = mapped(cwd) if isinstance(cwd, str) else None
            if new is None or new == cwd:
                out.append(line)
                continue
            changed[cwd] = changed.get(cwd, 0) + 1
            rec["cwd"] = new
            out.append(json.dumps(rec, separators=(",", ":")) + ("\n" if line.endswith("\n") else ""))
    return out, changed


def count(path: Path, mapped: Callable[[str], str | None]) -> dict[str, int]:
    """What rewrite_file would change, without writing."""
    return _lines(path, mapped)[1]


def rewrite_file(path: Path, mapped: Callable[[str], str | None], backup: Path | None) -> dict[str, int]:
    """Rewrite one JSONL file's cwd fields in place, after copying it into the folder `backup`."""
    out, changed = _lines(path, mapped)
    if changed:
        if backup is not None:
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, backup / path.name)
        atomic_write_text(path, "".join(out), errors=LOSSLESS)
    return changed


def session_files(session_dir: Path, transcript: Path) -> list[Path]:
    """The main transcript and its subagents' transcripts (not symlinks), which carry cwd fields too."""
    sub = session_dir / "subagents"
    return (
        [transcript, *(p for p in sorted(sub.glob("*.jsonl")) if not p.is_symlink())] if sub.is_dir() else [transcript]
    )
