"""`claudestra install login-unit`: the login unit (DESIGN.md §7).

The unit records the exact paths of claudestra and claude found when it is installed, since the systemd
user manager's PATH need not hold either; when claude moves, the unit is reinstalled.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

from ..caller import Refused
from ..runners import UNIT

PACKAGE = Path(__file__).resolve().parents[3]  # scripts/claudestra


def cam_command() -> list[str]:
    """How the unit runs claudestra: the installed `claudestra` if there is one, else through uv from the package."""
    exe = shutil.which("claudestra")
    # Not the package's own .venv, which uv rebuilds per machine; the `uv tool install` one, or uv.
    if exe and not Path(exe).resolve().is_relative_to(PACKAGE):
        return [exe]
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    return [uv, "run", "--quiet", "--project", str(PACKAGE), "claudestra"]


def claude_path() -> str:
    exe = shutil.which("claude")
    if not exe:
        raise Refused("claude is not on PATH, so the unit cannot record where it is")
    return str(Path(exe).absolute())


def unit_text(cmd: list[str], claude: str) -> str:
    return f"""# Written by `claudestra install login-unit` (DESIGN.md §7). It records the exact paths of claudestra
# and claude found when it was installed, since this manager's PATH need not hold them. If claude
# moves, or the unit fails with "claude is not at …", reinstall the unit to record the new path.
[Unit]
Description=Start this machine's managing Claude Code sessions in claudestra's tmux session
Documentation=file://{PACKAGE.parent / "DESIGN.md"}
After=graphical-session.target network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart={shlex.join([*cmd, "autostart", "--claude", claude])}
KillMode=process

[Install]
WantedBy=graphical-session.target
"""


def expected() -> str:
    return unit_text(cam_command(), claude_path())


def unit_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user" / UNIT


def install(dry: bool) -> list[str]:
    path, text = unit_path(), expected()
    out = [f"{'would write' if dry else 'write'} {path}:", *("    " + line for line in text.splitlines())]
    if path.exists() and path.read_text() == text:
        out.append("already installed and current")
    if dry:
        out.append(f"would run: systemctl --user daemon-reload; systemctl --user enable {UNIT}")
        return out
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    for args in (["daemon-reload"], ["enable", UNIT]):
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)
        out.append(f"systemctl --user {' '.join(args)}: " + ("ok" if r.returncode == 0 else r.stderr.strip()))
    out.append(f"it runs at the next login; `systemctl --user start {UNIT}` runs it now")
    return out


def uninstall(dry: bool) -> list[str]:
    """Disable and remove the login unit; it stops nothing that is running."""
    path = unit_path()
    if not path.exists():
        return []
    if dry:
        return [f"would run: systemctl --user disable {UNIT}", f"would remove {path}"]
    out = []
    r = subprocess.run(["systemctl", "--user", "disable", UNIT], capture_output=True, text=True)
    out.append(f"systemctl --user disable {UNIT}: " + ("ok" if r.returncode == 0 else r.stderr.strip()))
    path.unlink()
    out.append(f"removed {path}")
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    return out
