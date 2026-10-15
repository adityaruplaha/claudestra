"""The tmux runner against a real tmux server on its own socket, with a stand-in for claude."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import pytest

from claudestra.caller import Caller, Refused
from claudestra.runners import tmux as runner

from conftest import HERE, HUMAN, A, B, Home

pytestmark = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake = tmp_path / "claude"
    # Records its arguments and environment, then waits; exits on Ctrl-C, as Claude Code does.
    fake.write_text(
        f'#!/bin/sh\necho "$@" > {tmp_path}/argv\nenv > {tmp_path}/env\ntrap "exit 0" INT\nwhile :; do sleep 1; done\n'
    )
    fake.chmod(0o755)
    # The caller's own Claude variables, which must never reach a staffer.
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "caller-session")
    monkeypatch.setattr(runner, "STARTUP_WAIT", 1.0)
    t = runner.Tmux(f"camtest-{uuid.uuid4().hex[:8]}")
    yield t, tmp_path, str(fake)
    t.server.cmd("kill-server")


def test_compact_a_stopped_session(home: Home, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Resumed in tmux, compacted when idle, stopped again; a running session is refused."""
    from claudestra.actions import wait
    from claudestra.session import Session

    tr = home.transcript(A, home.folder("w"))
    home.staff_file(A, "one", {HERE: "~/w"})
    sessions = home.home / ".claude" / "sessions"
    sessions.mkdir(parents=True)
    fake = tmp_path / "claude-compacting"
    # A stand-in that registers a live session file, idles, records a compaction when it reads
    # /compact, and removes its file on Ctrl-C, as Claude Code does on a clean exit.
    fake.write_text(f"""#!/bin/sh
start=$(awk '{{print $22}}' /proc/$$/stat)
printf '{{"pid":%s,"sessionId":"%s","procStart":"%s","status":"idle","kind":"interactive","cwd":"%s"}}' $$ "$2" "$start" "$PWD" > {sessions}/$$.json
trap 'rm {sessions}/$$.json; exit 0' INT
printf '\\342\\235\\257 \\n'
while IFS= read -r line; do
  case "$line" in /compact*) printf '{{"type":"system","subtype":"compact_boundary","note":"%s"}}\\n' "$line" >> {tr};; esac
done
""")
    fake.chmod(0o755)
    monkeypatch.setattr(wait, "POLL", 0.1)
    socket = f"camtest-{uuid.uuid4().hex[:8]}"
    t = runner.Tmux(socket)
    try:
        c = home.acting(HUMAN)
        out = Session(A).compact(str(fake), "keep the decisions", timeout=10, socket=socket).perform()
        assert out[0].startswith("started") and out[1] == f"compacted {A}" and out[2].startswith("stopped")
        assert '"note":"/compact keep the decisions"' in tr.read_text()
        assert t.window(A) is None and not list(sessions.glob("*.json"))
        c._subject = Caller("unscoped", B, "x", 1)
        with pytest.raises(Refused, match="relation to it is none"):
            Session(A).compact(str(fake), socket=socket).perform()
    finally:
        t.server.cmd("kill-server")
