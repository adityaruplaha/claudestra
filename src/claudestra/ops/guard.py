"""`claudestra install guard`: what keeps sessions out of claudestra's config (DESIGN.md §6.5).

Two layers, both in the user's own Claude Code settings. **Deny rules** for the Read and Edit tools and the
shell's common file commands; a rule does not expand variables, so a config folder away from
`~/.config/claudestra` is written as its resolved path as well. And a **`PreToolUse` hook**, `guard.py` in
the config folder, which refuses a tool call that names the folder, catching an interpreter that opens a
file there, which the rules miss, and refuses an edit of the settings that would take the hook out. The
hook holds in every permission mode, bypass included. Where the user has turned the sandbox on, the folder
is hidden from it too, and claudestra itself is run outside it so that it can still read its config.

Installing only adds protection, so anyone may run it, the plugin's `SessionStart` hook included; nothing
in claudestra takes it away. `--managed` prints the same for managed settings, which no session can
change, but which need root to install.
"""

from __future__ import annotations

import copy
import json
import shlex
import sys
from pathlib import Path

from ..caller import Refused
from ..claude_fs import ClaudeFS
from ..portable import atomic_write_text

DEFAULT = "/home/*/.config/claudestra"  # every user's default config folder; `*` does not cross a /
TOOLS = ("Read", "Edit")  # a Read deny also blocks writes; Edit covers every editing tool
COMMANDS = ("claudestra *", "clost *")  # run outside the sandbox; a bare name matches no command with arguments
MATCHER = "Bash|Read|Edit|MultiEdit|Write|NotebookEdit|Grep|Glob"
GUARD = "guard.py"
MANAGED = Path("/etc/claude-code")
DROP_IN = MANAGED / "managed-settings.d" / "claudestra.json"

# The same on every machine, so a config folder kept in step between machines carries it unchanged: it
# finds the config folder from where it lies, and the home folder and Claude Code's settings as it runs.
# A shell command is refused for a path-like word that resolves into the folder, not for any mention of
# its name, so a command that only mentions it (grepping docs for it, say) runs.
GUARD_SOURCE = r'''"""Written by `claudestra install guard`, which rewrites it: a Claude Code PreToolUse hook that refuses a
session's tool call touching claudestra's config folder, the one this file lies in, or an edit of the
settings that would remove this hook (claudestra's DESIGN.md §6.5). It fails open on input it cannot
read, rather than block every call."""

import json
import os
import re
import sys

HOOK = os.path.abspath(__file__)  # as the settings name it, which an edit of them must keep
CONFIG = os.path.realpath(os.path.dirname(HOOK))
CLAUDE = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
SETTINGS = os.path.realpath(os.path.join(CLAUDE, "settings.json"))
# The words of a shell command: what lies between spaces, quotes and shell operators; and the path-like
# runs inside a word, from the root, the home folder or a variable (`x>$HOME/...`, `--to=/...`). Each is
# resolved, a relative one against the session's folder; a word that only mentions the folder's name
# resolves elsewhere and passes.
WORD = re.compile(r"""[^\s'"`;|&<>()]+""")
PATH = re.compile(r"""(?:~|\$\{?[A-Za-z_]\w*\}?|/)[^\s'"`;|&<>()=]*""")


def inside(p, cwd=None):
    p = os.path.expanduser(os.path.expandvars(p))
    p = os.path.realpath(os.path.join(cwd, p) if cwd else p)
    return p == CONFIG or p.startswith(CONFIG + os.sep)


def refuse(tool, i, cwd):
    if cwd and inside(cwd):
        return True
    if tool == "Bash":
        command = str(i.get("command", ""))
        words = [m.group() for m in WORD.finditer(command)] + [m.group() for m in PATH.finditer(command)]
        return any(inside(w, cwd) for w in words)
    paths = [str(i[k]) for k in ("file_path", "path", "notebook_path") if i.get(k)]
    if any(inside(p, cwd) for p in paths):
        return True
    if any(os.path.realpath(os.path.expanduser(p)) == SETTINGS for p in paths):
        if tool == "Write":
            return HOOK not in str(i.get("content", ""))
        edits = [i, *(i.get("edits") or [])]
        before = "".join(str(e.get("old_string", "")) for e in edits)
        after = "".join(str(e.get("new_string", "")) for e in edits)
        return HOOK in before and HOOK not in after
    return False


try:
    call = json.load(sys.stdin)
    hit = refuse(call.get("tool_name"), call.get("tool_input") or {}, call.get("cwd"))
except Exception:
    hit = False
if hit:
    print(f"claudestra: a session may not touch claudestra's config ({CONFIG}) or its guard; use claudestra's commands", file=sys.stderr)
    sys.exit(2)
'''


def folders(config: Path) -> list[str]:
    """The config folder as the rules name it: the default for every user, and this one where it is elsewhere."""
    config = config.absolute()
    p = config.parts
    default = len(p) == 5 and p[1] == "home" and p[3:] == (".config", "claudestra")
    return [DEFAULT] if default else [DEFAULT, str(config)]


def rules(config: Path) -> list[str]:
    return [f"{tool}(/{folder}/**)" for folder in folders(config) for tool in TOOLS]


def settings_path(fs: ClaudeFS) -> Path:
    return fs.root / "settings.json"


def guard_path(config: Path) -> Path:
    return config.absolute() / GUARD


def hook_command(config: Path) -> str:
    """The hook as the settings run it: this Python, isolated and without site, so it starts quickly."""
    return shlex.join([sys.executable, "-I", "-S", str(guard_path(config))])


def hook_entry(config: Path) -> dict:
    return {"matcher": MATCHER, "hooks": [{"type": "command", "command": hook_command(config)}]}


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise Refused(f"cannot read {path}: {e}") from e
    if not isinstance(data, dict):
        raise Refused(f"{path} does not hold a JSON object")
    return data


def _obj(where: dict, key: str, what: str) -> dict:
    v = where.setdefault(key, {})
    if not isinstance(v, dict):
        raise Refused(f"{what} in the settings is not an object")
    return v


def _list(where: dict, key: str, what: str) -> list:
    v = where.setdefault(key, [])
    if not isinstance(v, list):
        raise Refused(f"{what} in the settings is not a list")
    return v


def _add(where: dict, key: str, items: list[str], what: str, out: list[str]) -> None:
    have = _list(where, key, what)
    for item in items:
        if item not in have:
            have.append(item)
            out.append(f"    {what}: {item}")


def _set_hook(settings: dict, config: Path, out: list[str]) -> None:
    """claudestra's PreToolUse entry, found by the guard's path and replaced if it differs; the rest kept."""
    entries = _list(_obj(settings, "hooks", "hooks"), "PreToolUse", "hooks.PreToolUse")
    want, guard = hook_entry(config), str(guard_path(config))
    ours = [e for e in entries if isinstance(e, dict) and guard in json.dumps(e)]
    if ours == [want]:
        return
    entries[:] = [e for e in entries if e not in ours] + [want]
    out.append(f"    hooks.PreToolUse: {want['hooks'][0]['command']}, on {MATCHER}")


def plan(fs: ClaudeFS, config: Path) -> tuple[Path, dict, list[str]]:
    """The user's settings with the guard added, and what changes, line by line (none if all is in place)."""
    path = settings_path(fs)
    settings = copy.deepcopy(_read(path))
    added: list[str] = []
    _add(_obj(settings, "permissions", "permissions"), "deny", rules(config), "permissions.deny", added)
    _set_hook(settings, config, added)
    sandbox = settings.get("sandbox")
    if isinstance(sandbox, dict) and sandbox.get("enabled") is True:
        hidden = _obj(sandbox, "filesystem", "sandbox.filesystem")
        for key in ("denyRead", "denyWrite"):
            _add(hidden, key, [str(config.absolute())], f"sandbox.filesystem.{key}", added)
        _add(sandbox, "excludedCommands", list(COMMANDS), "sandbox.excludedCommands", added)
    return path, settings, added


def install(fs: ClaudeFS, config: Path, dry: bool) -> list[str]:
    path, settings, added = plan(fs, config)
    guard, text = guard_path(config), GUARD_SOURCE
    stale = not guard.is_file() or guard.read_text() != text
    if not added and not stale:
        return [f"the guard is in place: {path} and {guard}"]
    out = [f"{'would write' if dry else 'write'} {guard}"] if stale else []
    if added:
        out += [f"{'would add to' if dry else 'add to'} {path}:", *added]
    if dry:
        return out
    if stale:  # the guard first, so that the hook never names a file that is not there
        config.mkdir(parents=True, exist_ok=True)
        atomic_write_text(guard, text)
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(settings, indent=2) + "\n")
    return out


def managed(config: Path) -> list[str]:
    """The drop-in for managed settings, and how the user installs it as root."""
    drop_in = {"permissions": {"deny": rules(config)}, "hooks": {"PreToolUse": [hook_entry(config)]}}
    return [
        "managed settings cannot be changed by any session, but need root. Run `claudestra install guard` first,",
        "which writes the hook this names, then install the drop-in:",
        f"  sudo install -D -m 644 /dev/stdin {DROP_IN} <<'EOF'",
        *json.dumps(drop_in, indent=2).splitlines(),
        "EOF",
    ]


def missing(fs: ClaudeFS, config: Path) -> list[str]:
    """What of the guard is in neither the user's settings nor managed settings, or is out of date."""
    sources = [settings_path(fs), MANAGED / "managed-settings.json", *sorted(MANAGED.glob("managed-settings.d/*.json"))]
    have: set[str] = set()
    hooked = False
    for path in sources:
        try:
            data = _read(path)
        except Refused:
            continue
        perms, hooks = data.get("permissions"), data.get("hooks")
        if isinstance(perms, dict) and isinstance(perms.get("deny"), list):
            have.update(r for r in perms["deny"] if isinstance(r, str))
        if isinstance(hooks, dict) and hook_entry(config) in (hooks.get("PreToolUse") or []):
            hooked = True
    out = [r for r in rules(config) if r not in have]
    if not hooked:
        out.append("the PreToolUse hook")
    guard = guard_path(config)
    if not guard.is_file() or guard.read_text() != GUARD_SOURCE:
        out.append(f"{guard} as claudestra writes it")
    return out


def uninstall(fs: ClaudeFS, config: Path, dry: bool) -> list[str]:
    """Take the guard out of the user's settings (its deny rules, its hook, and what it added to the sandbox),
    keeping everything else there, and remove `guard.py`. Managed settings are root's, and are only named."""
    path = settings_path(fs)
    settings = _read(path)
    before = json.dumps(settings, sort_keys=True)
    out: list[str] = []
    perms = settings.get("permissions")
    if isinstance(perms, dict) and isinstance(perms.get("deny"), list):
        perms["deny"] = [r for r in perms["deny"] if r not in rules(config)]
    hooks = settings.get("hooks")
    if isinstance(hooks, dict) and isinstance(hooks.get("PreToolUse"), list):
        g = str(guard_path(config))
        hooks["PreToolUse"] = [e for e in hooks["PreToolUse"] if not (isinstance(e, dict) and g in json.dumps(e))]
    sandbox = settings.get("sandbox")
    if isinstance(sandbox, dict):
        fs_ = sandbox.get("filesystem")
        for key in ("denyRead", "denyWrite"):
            if isinstance(fs_, dict) and isinstance(fs_.get(key), list):
                fs_[key] = [p for p in fs_[key] if p != str(config.absolute())]
        if isinstance(sandbox.get("excludedCommands"), list):
            sandbox["excludedCommands"] = [x for x in sandbox["excludedCommands"] if x not in COMMANDS]
    if json.dumps(settings, sort_keys=True) != before:
        out.append(f"{'would take' if dry else 'take'} the guard's rules and hook out of {path}")
        if not dry:
            atomic_write_text(path, json.dumps(settings, indent=2) + "\n")
    g = guard_path(config)
    if g.exists():
        out.append(f"{'would remove' if dry else 'remove'} {g}")
        if not dry:
            g.unlink()
    if DROP_IN.exists():
        out.append(f"{DROP_IN} is root's: remove it with `sudo rm {DROP_IN}`")
    return out
