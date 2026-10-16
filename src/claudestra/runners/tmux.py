"""The tmux runner (DESIGN.md §7): one tmux session, one window per staffer, named
by its session ID.

`remain-on-exit` is set before the staffer starts, so one that exits at once leaves its window and
status behind; the window cannot be renamed; the desktop variables reach it for graphical pinentry,
and a PATH holding claude and claudestra; and no Claude Code variable reaches it, so it is not taken for a
child of whoever ran claudestra.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shlex
import shutil
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import libtmux

from .. import portable
from ..caller import Refused, filed_under, transcript_problem
from ..claude_fs import ClaudeFS
from . import TMUX_SESSION, Launch

DESKTOP_VARS = ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_TYPE")
HOLD = "sleep 2147483647"  # a window's placeholder until its options are set
STARTUP_WAIT = 20.0  # seconds to wait for Claude Code to write the new run's session file
RENAME_WAIT = 10.0  # seconds to wait for a typed /rename to reach custom-title.json
ANSI = re.compile(r"\x1b\[[0-9;]*m")
DIM = "\x1b[2m"
LEAD = re.compile(r"^(?:[ \xa0]|\x1b\[(?!2m)[0-9;]*m)*")  # spaces, and any styling but dim


OPTION = "@claudestra_session"  # the window option holding its session's ID; its name is the session's name


@dataclass
class Window:
    id: str
    name: str  # what tmux shows: the session's name
    dead: bool
    status: str
    pid: int | None
    session: str = ""  # its session's ID, from the window option, or from the name a window had before 0.2.0


class Tmux:
    def __init__(self, socket_name: str | None = None):
        self.session = TMUX_SESSION
        self.socket_name = socket_name
        self.server = libtmux.Server(socket_name=socket_name)

    def run(self, *args: str, check: bool = True) -> list[str]:
        r = self.server.cmd(*args)
        if check and r.stderr:
            raise Refused(f"tmux {' '.join(args[:2])}: {' '.join(r.stderr)}")
        return r.stdout

    def exists(self) -> bool:
        return self.server.cmd("has-session", "-t", f"={self.session}").returncode == 0

    def windows(self) -> list[Window]:
        if not self.exists():
            return []
        fmt = "#{window_id}\t#{pane_dead}\t#{pane_dead_status}\t#{pane_pid}\t#{" + OPTION + "}\t#{window_name}"
        out = []
        for line in self.run("list-windows", "-t", f"={self.session}", "-F", fmt):
            wid, dead, status, pid, sid, name = line.split("\t", 5)
            out.append(Window(wid, name, dead == "1", status, int(pid) if pid.isdigit() else None, sid or name))
        return out

    def window(self, session_id: str) -> Window | None:
        """A session's window, found by the session ID it holds, which a rename does not change.

        Matched here exactly: tmux would read a target as a pattern."""
        return next((w for w in self.windows() if w.session == session_id), None)

    def name_window(self, wid: str, name: str) -> None:
        """Show the session's name on its window; the ID it is found by stays in its option."""
        self.run("rename-window", "-t", wid, name)

    def screen(self, wid: str, lines: int) -> list[str]:
        """The window's last `lines` lines of screen and scrollback, as plain text, trailing blank lines dropped."""
        rows = self.run("capture-pane", "-p", "-J", "-S", f"-{lines}", "-t", wid)
        while rows and not rows[-1].strip():
            rows.pop()
        return rows[-lines:]

    def unsent(self, wid: str) -> str:
        """Text typed into Claude Code's prompt in the window and not sent, or "" when there is none.

        The prompt is the last line beginning with ❯, and runs to the rule drawn under it. Claude Code
        shows a suggestion there dimmed; typing replaces it, so it does not count as text.
        """
        rows = self.run("capture-pane", "-e", "-p", "-t", wid)
        plain = [ANSI.sub("", r) for r in rows]
        at = next((i for i in range(len(plain) - 1, -1, -1) if plain[i].lstrip().startswith("❯")), None)
        if at is None:
            raise Refused("no Claude Code prompt is showing in its window; look at it with `claudestra session attach`")
        rest = LEAD.sub("", rows[at].split("❯", 1)[1])
        typed = [] if rest.startswith(DIM) or not ANSI.sub("", rest).strip() else [ANSI.sub("", rest).strip()]
        for line in plain[at + 1 :]:
            if line.lstrip().startswith("─"):
                break
            if line.strip():
                typed.append(line.strip())
        return "\n".join(typed)

    def claude_vars(self) -> list[str]:
        """Claude Code's variables in the server's global environment, once there is a server."""
        lines = self.run("show-environment", "-g", check=False) if self.exists() else []
        return [n for line in lines if (n := line.split("=", 1)[0].lstrip("-")).startswith("CLAUDE")]


def launch_path(claude: str) -> str:
    """PATH for a session claudestra starts: the folders holding claude and claudestra first, then claudestra's own PATH.

    The login unit runs under the systemd user manager's PATH, which need not hold either, and a
    staffer calls both."""
    claudestra = shutil.which("claudestra") or (
        sys.argv[0] if os.path.basename(sys.argv[0]) in ("claudestra", "clost") else None
    )
    first = [str(Path(x).absolute().parent) for x in (claude, claudestra) if x]
    rest = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d]
    return os.pathsep.join(dict.fromkeys(first + rest))


def drop_claude_env() -> None:
    """Remove Claude Code's variables from this process, so a tmux server it starts lacks them too."""
    for k in [k for k in os.environ if k.startswith("CLAUDE")]:
        del os.environ[k]


def start(fs: ClaudeFS, host: str, t: Tmux, launch: Launch, claude: str, dry: bool) -> str:
    """Resume the session in a window of its own, named by its session ID. Who may is the action's to
    decide (actions/start.py); this checks only that it can be done."""
    w = t.window(launch.session)
    if w and not w.dead:
        return f"running   {launch.name}"
    if pid := portable.running_pid(fs.sessions, fs.proc, launch.session):
        raise Refused(
            f"{launch.name!r} is already running outside claudestra's tmux (pid {pid}); resuming it would fork it"
        )
    if launch.new:
        if filed_under(fs, launch.session):
            raise Refused(f"session {launch.session} exists already")
    elif why := transcript_problem(fs, host, launch.session, launch.folder):
        raise Refused(why)
    if not launch.folder.is_dir():
        raise Refused(f"{launch.folder} does not exist")
    if not Path(claude).is_file():
        raise Refused(
            f"claude is not at {claude}; if the login unit named that path, reinstall it with `claudestra install login-unit`"
        )

    if launch.new:
        argv = [claude, "--session-id", launch.session, "--name", launch.name, "--remote-control", launch.name]
        argv += [launch.prompt] if launch.prompt else []
    else:
        argv = [claude, "--resume", launch.session, "--remote-control", launch.name]
    env = {v: os.environ[v] for v in DESKTOP_VARS if os.environ.get(v)}
    if dry:
        return f"would start  {launch.name}  in {launch.folder}:  {shlex.join(argv)}"
    drop_claude_env()
    if w:
        wid = w.id
    elif t.exists():
        wid = t.run(
            "new-window",
            "-d",
            "-P",
            "-F",
            "#{window_id}",
            "-t",
            f"={t.session}:",
            "-n",
            launch.session,
            "-c",
            str(launch.folder),
            HOLD,
        )[0]
    else:
        t.server.new_session(
            session_name=t.session,
            window_name=launch.session,
            start_directory=str(launch.folder),
            window_command=HOLD,
            attach=False,
        )
        wid = t.window(launch.session).id
    for opt, val in (("remain-on-exit", "on"), ("automatic-rename", "off"), ("allow-rename", "off")):
        t.run("set-option", "-w", "-t", wid, opt, val)
    t.run("set-option", "-w", "-t", wid, OPTION, launch.session)  # found by this from now on
    t.name_window(wid, launch.name)
    # Asked of the server only now that it exists: one started earlier, by anyone, may hold them.
    # PATH goes on env's command line: the shell tmux runs the command in, and tmux itself, would
    # otherwise put back their own.
    command = shlex.join(
        ["env", *(x for n in sorted(set(t.claude_vars())) for x in ("-u", n)), f"PATH={launch_path(claude)}", *argv]
    )
    t.run(
        "respawn-window",
        "-k",
        "-t",
        wid,
        "-c",
        str(launch.folder),
        *(x for k, v in env.items() for x in ("-e", f"{k}={v}")),
        command,
    )
    deadline = time.monotonic() + STARTUP_WAIT
    while time.monotonic() < deadline:
        if pid := portable.running_pid(fs.sessions, fs.proc, launch.session):
            return f"started   {launch.name} (pid {pid})"
        if (now := t.window(launch.session)) and now.dead:
            return f"exited    {launch.name} at once (status {now.status}); its window is kept for `claudestra session attach`"
        time.sleep(0.25)
    return f"started   {launch.name}; no session file after {STARTUP_WAIT:g}s, so `claudestra ls` may show it stopped for a moment"


def stop(fs: ClaudeFS, t: Tmux, sid: str, name: str, dry: bool, force: bool) -> str:
    """Stop the session's window: two Ctrl-Cs, then SIGTERM. Who may is the action's to decide."""
    w = t.window(sid)
    if not w:
        if pid := portable.running_pid(fs.sessions, fs.proc, sid):
            return f"not here  {name} (it runs outside claudestra's tmux, pid {pid}; stop it there)"
        return f"not here  {name}"
    if w.dead:
        if dry:
            return f"would clear  {name} (it had exited, status {w.status})"
        t.run("kill-window", "-t", w.id)
        return f"cleared   {name} (it had exited, status {w.status})"
    pf = fs.live_pid_file(w.pid) if w.pid else None
    if pf and pf.get("status") == "busy" and not force:
        raise Refused(f"{name!r} is in the middle of a turn; wait, or pass --force")
    if dry:
        return f"would stop  {name} (pid {w.pid})"
    # Claude Code exits on a second Ctrl-C; the conversation is kept and can be resumed.
    for _ in range(2):
        t.run("send-keys", "-t", w.id, "C-c")
        time.sleep(0.5)
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and (now := t.window(sid)) is not None and not now.dead:
        time.sleep(0.5)
    now = t.window(sid)
    if now and not now.dead and now.pid:
        with contextlib.suppress(ProcessLookupError):
            os.kill(now.pid, signal.SIGTERM)
        time.sleep(3)
        now = t.window(sid)
    if now and not now.dead:
        raise Refused(f"{name!r} (pid {now.pid}) did not exit; its window is left as it was")
    if now:
        t.run("kill-window", "-t", now.id)
    return f"stopped   {name}"


def running_window(fs: ClaudeFS, t: Tmux, session_id: str) -> tuple[int | None, Window | None]:
    """The session's live pid, and the window in claudestra's tmux it runs in, matched by pid, not name."""
    pid = portable.running_pid(fs.sessions, fs.proc, session_id)
    return pid, next((w for w in t.windows() if pid and not w.dead and w.pid == pid), None)


def ready(fs: ClaudeFS, t: Tmux, w: Window, sid: str) -> None:
    """Refuse a window whose session is mid-turn, or whose prompt holds unsent text."""
    pf = fs.live_pid_file(w.pid) if w.pid else None
    if pf and pf.get("status") == "busy":
        raise Refused(f"{sid} is in the middle of a turn; wait for it to finish")
    if typed := t.unsent(w.id):
        raise Refused(f"{sid}'s prompt holds unsent text ({typed[:60]!r}); send or clear it first")


def check_text(text: str) -> str:
    if not text.strip() or "\n" in text or "\r" in text:
        raise Refused("the text is one line, not empty: Enter sends it")
    return text


def window_to_type_into(fs: ClaudeFS, t: Tmux, sid: str) -> Window:
    """The window of a session running in claudestra's tmux, idle, with nothing typed in it."""
    pid, w = running_window(fs, t, sid)
    if not w:
        raise Refused(
            f"{sid} is not running in claudestra's tmux" + (f" (it runs as pid {pid} elsewhere)" if pid else "")
        )
    ready(fs, t, w, sid)
    return w


def type_into(fs: ClaudeFS, t: Tmux, sid: str, w: Window, text: str) -> None:
    """Type one line into the window and press Enter, checking again first, since time has passed."""
    if running_window(fs, t, sid)[1] != w:
        raise Refused(f"{sid} is no longer running in window {w.id}; run it again")
    ready(fs, t, w, sid)
    t.run("send-keys", "-t", w.id, "-l", check_text(text))
    t.run("send-keys", "-t", w.id, "Enter")


def rename_in_window(fs: ClaudeFS, t: Tmux, sid: str, title: Path, w: Window, name: str) -> None:
    """Type /rename into the window and wait until custom-title.json carries the new name."""
    type_into(fs, t, sid, w, f"/rename {name}")
    deadline = time.monotonic() + RENAME_WAIT
    while time.monotonic() < deadline:
        with contextlib.suppress(OSError, ValueError):
            if json.loads(title.read_text()).get("customTitle") == name:
                t.name_window(w.id, name)
                return
        time.sleep(0.25)
    raise Refused(
        f"typed /rename into {w.id}, but it had not taken after {RENAME_WAIT:g}s; look with `claudestra session attach`"
    )
