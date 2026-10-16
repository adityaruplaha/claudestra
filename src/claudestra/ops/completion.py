"""Shell completion for `claudestra` and `clost`, installed into the user's own shell (DESIGN.md §10).

The script comes from typer, made to cover `clost` too, since click looks for a variable named after the
command (`_CLOST_COMPLETE`) and the script sets only claudestra's. zsh and bash source it from their startup
file, by one marked line that does nothing where completion is not loaded; fish loads it from its
completions folder. Installing only adds completion, so anyone may do it, and claudestra's plugin does
when a session starts.
"""

from __future__ import annotations

import os
from pathlib import Path

from typer._completion_shared import get_completion_script

from ..portable import atomic_write_text

SHELLS = ("zsh", "bash", "fish")
MARK = "# claudestra: shell completion"


def user_shell() -> str | None:
    name = os.path.basename(os.environ.get("SHELL", ""))
    return name if name in SHELLS else None


def script(shell: str) -> str:
    s = get_completion_script(prog_name="claudestra", complete_var="_CLAUDESTRA_COMPLETE", shell=shell)
    if shell == "zsh":
        return s.rstrip() + "\ncompdef _claudestra_completion clost\n"
    if shell == "bash":
        s = s.replace("_CLAUDESTRA_COMPLETE=complete_bash $1", "_CLAUDESTRA_COMPLETE=complete_bash claudestra")
        return s.rstrip() + "\ncomplete -o default -F _claudestra_completion clost\n"
    return s.rstrip() + "\n" + s.strip().replace("--command claudestra", "--command clost", 1) + "\n"


def _data(home: Path) -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")


def files(shell: str, home: Path) -> tuple[Path, Path | None]:
    """Where the script goes, and the startup file that sources it (none for fish)."""
    if shell == "fish":
        conf = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
        return conf / "fish" / "completions" / "claudestra.fish", None
    rc = Path(os.environ.get("ZDOTDIR") or home) / ".zshrc" if shell == "zsh" else home / ".bashrc"
    return _data(home) / "claudestra" / f"completion.{shell}", rc


def line(shell: str, target: Path) -> str:
    loaded = "(( $+functions[compdef] ))" if shell == "zsh" else "type complete >/dev/null 2>&1"
    return f'{loaded} && [ -r "{target}" ] && source "{target}"  {MARK}'


def installed(shell: str | None, home: Path) -> str | None:
    """Where it is installed and current, or None if it is not."""
    if shell is None:
        return None
    target, rc = files(shell, home)
    if not target.is_file() or target.read_text() != script(shell):
        return None
    if rc is not None and line(shell, target) not in (rc.read_text() if rc.is_file() else ""):
        return None
    return f"in {target}" + (f", sourced by {rc}" if rc else "")


def install(shell: str, home: Path, dry: bool) -> list[str]:
    target, rc = files(shell, home)
    out = []
    if not target.is_file() or target.read_text() != script(shell):
        out.append(f"{'would write' if dry else 'write'} {target}")
        if not dry:
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(target, script(shell))
    if rc is not None:
        text = rc.read_text() if rc.is_file() else ""
        want = line(shell, target)
        if want not in text:
            kept = [x for x in text.splitlines() if not x.endswith(MARK)]  # an older line of ours goes
            out.append(f"{'would add' if dry else 'add'} to {rc}: {want}")
            if not dry:  # written where it really is, so a startup file kept as a symlink stays one
                atomic_write_text(rc.resolve(), "\n".join([*kept, want]) + "\n")
    return out or [f"completion for {shell} is in place"]


def uninstall(home: Path, dry: bool) -> list[str]:
    """Remove completion from every shell it was installed in: the script, and the marked startup line."""
    out = []
    for shell in SHELLS:
        target, rc = files(shell, home)
        if target.exists():
            out.append(f"{'would remove' if dry else 'remove'} {target}")
            if not dry:
                target.unlink()
        if rc is not None and rc.is_file() and MARK in (text := rc.read_text()):
            out.append(f"{'would take' if dry else 'take'} claudestra's line out of {rc}")
            if not dry:
                kept = [x for x in text.splitlines() if not x.endswith(MARK)]
                atomic_write_text(rc.resolve(), "\n".join(kept) + "\n")
    return out
