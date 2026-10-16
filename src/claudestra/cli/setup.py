"""`claudestra setup`, the first-run walk-through at the user's terminal, and `claudestra preferences`.

It takes each step only where it is not done yet, shows its plan and asks before it acts: this machine
in trust.yaml, the guard, Remote Control, a device-scope manager that starts at login, the login unit,
shell completion, and the user's preferences. Each step is an action of its own, authorized as itself,
so it can do nothing a user could not do with the commands one by one (DESIGN.md §6.6).
"""

from __future__ import annotations

import json
import shutil
from typing import Annotated

import questionary
import typer
from rich.text import Text

from .. import checks
from ..actions.preferences import SetPreference, ShowPreferences
from ..actions.trust_autostart import TrustAutostart
from ..actions.trust_grant import TrustGrant
from ..actions.trust_machine import TrustMachine
from ..caller import Refused
from ..ops import completion, guard, remote_control
from ..ops import preferences as prefs
from ..trust import machine_problem
from . import select
from .base import Ctx, app, refusing
from .ui import AsJson, Dry, Yes, err, fail, go_ahead, interactive, lines, out


def _value(key: str) -> select.OneOf:
    pref = prefs.PREFERENCES[key]
    return select.OneOf(pref.choices, "a value", pref.question)


@app.command()
def preferences(
    key: Annotated[str | None, typer.Argument(help=f"One of {', '.join(prefs.PREFERENCES)}, to set it.")] = None,
    value: Annotated[str | None, typer.Argument(help="One of its choices; picked at a terminal if left out.")] = None,
    dry: Dry = False,
    yes: Yes = False,
    as_json: AsJson = False,
) -> None:
    """The user's preferences, which sessions follow. Bare, show them (anyone); with a preference, set it (the user's alone)."""
    if key is None and as_json:
        shown = refusing(ShowPreferences().perform)
        print(
            json.dumps(
                {
                    k: {"value": v, "means": prefs.PREFERENCES[k].choices[v] if v else prefs.PREFERENCES[k].unset}
                    for k, v in shown.items()
                },
                indent=2,
            )
        )
        return
    if key is None:
        for k, v in refusing(ShowPreferences().perform).items():
            pref = prefs.PREFERENCES[k]
            meaning = pref.choices[v] if v else f"not chosen, so {pref.unset}"
            out.print(Text.assemble((f"{k}: ", "bold"), (v or "-", ""), (f"  ({meaning})", "dim")))
        return
    if key not in prefs.PREFERENCES:
        raise fail(f"refused: no preference {key!r}; there are {', '.join(prefs.PREFERENCES)}")
    value = _value(key).get(value)
    refusing(lambda: SetPreference(key, value).perform(go_ahead(yes, dry)))


# --- install ---------------------------------------------------------------------------------------------


def _step(title: str, done: str | None) -> bool:
    """Print the step; True if it is still to do."""
    if done:
        out.print(Text.assemble(("done  ", "green"), (title, "bold"), (f"  {done}", "dim")))
        return False
    out.print(Text.assemble(("to do ", "yellow"), (title, "bold")))
    return True


def _do(action, dry: bool) -> bool:
    """Perform one step's action, asking first; whether it ran. A refusal is said, and setup goes on."""
    try:
        action.perform(go_ahead(False, dry))
        return not dry
    except Refused as e:
        err.print(Text(f"refused: {e}", style="bold red"))
        return False
    except typer.Exit:  # declined at the question
        return False


@app.command()
def setup(ctx: typer.Context, dry: Dry = False) -> None:
    """Set claudestra up on this machine, a step at a time, skipping what is done (the user, at a terminal)."""
    c: Ctx = ctx.obj
    if not interactive():
        raise fail(
            "setup asks its questions at a terminal; run it there, or run each `claudestra install` step on its own"
        )
    if c.subject.kind != "human" or c.restricted:
        raise fail("setup is the user's, at a terminal with no Claude process in the chain that called it")
    host = c.machine.hostname

    known = c.trust.machines.get(host.lower())
    why = machine_problem(host, c.machine.machine_id, c.trust.machines)
    if _step("this machine in trust.yaml", None if why else host):
        if known is not None:
            err.print(Text(f"{why}; fix it with `claudestra trust machine remove` and `add`", style="bold red"))
        else:
            ssh = select.Text(
                "Its ssh address (user@host), if other machines connect to it; else leave empty:", ""
            ).get()
            _do(TrustMachine(True, ssh=ssh.strip() or None), dry)

    if _step("the guard", None if guard.missing(c.fs, c.trust.config) else "sessions are kept out of the config"):
        _do(c.install_guard(), dry)

    rc = remote_control.effective(c.fs)
    if _step("Remote Control for every session", f"on, by {rc[1]}" if rc[0] is True else None):
        _do(c.enable_remote_control(), dry)

    c.refresh()
    devices = c.trust.device_managers()
    if _step("a device-scope manager", ", ".join(d.name for d in devices) or None):
        _device_manager(c, dry)
        c.refresh()

    for d in c.trust.device_managers():
        if (
            d.session not in c.trust.autostart(host)
            and questionary.confirm(f"Start {d.name} at login?", default=True).ask()
        ):
            _do(TrustAutostart(d.session, True), dry)
    c.refresh()

    if c.trust.autostart(host):
        r = checks.check_login_unit(c.fs, False, c.trust, c.machine)
        if _step("the login unit", r.detail if r.status == checks.PASS else None):
            _do(c.install_login_unit(), dry)

    shell = completion.user_shell()
    done = completion.installed(shell, c.fs.home) if shell else "no completion for this shell"
    if _step(f"shell completion ({shell or 'unknown shell'})", done):
        _do(c.install_completion(shell), dry)

    for key, value in prefs.load(c.trust.config).items():
        pref = prefs.PREFERENCES[key]
        if _step(f"preference: {key}", f"{value} ({pref.choices[value]})" if value else None):
            _do(SetPreference(key, _value(key).get()), dry)

    out.print(Text("\nsetup has done what it can; `claudestra doctor` checks the rest.", style="bold"))


def _device_manager(c: Ctx, dry: bool) -> None:
    """A device-scope manager for this machine: a staffer here given device scope, or a new one spawned."""
    here = [sf for sf in c.trust.staff if sf.folder is not None and c.trust.scope(sf.session) is None]
    rows = [("new", f"spawn a new session in {c.fs.home}")]
    rows += [(sf.session, f"{sf.name} ({sf.session[:8]})") for sf in here]
    rows += [("", "not now")]
    got = select.pick("Which session manages this machine?", rows, "a session") or None
    if got is None:
        return
    if got == "new":
        claude = shutil.which("claude")
        if not claude:
            err.print(Text("claude is not on PATH, so no session can be spawned", style="bold red"))
            return
        name = select.Text("Its name:", "its name", f"{c.machine.hostname} manager").get()
        spawn = c.spawn(
            c.fs.home,
            claude,
            "You are being made this machine's device-scope manager under claudestra; the scope is granted just "
            "after you start. Wait for the user's first message, then read the claudestra skill and run "
            "`claudestra whoami` and `claudestra preferences` before anything else.",
            name,
            True,
            f"Manages the sessions on {c.machine.hostname}: organising them, and running what no folder manager holds.",
        )
        if not _do(spawn, dry) or dry:
            return
        got = spawn.session.id
        c.refresh()
    _do(TrustGrant(got, "device"), dry)


@app.command()
def uninstall(dry: Dry = False, yes: Yes = False) -> None:
    """Take out the guard, shell completion and the login unit, so removing claudestra leaves nothing broken (the user only)."""
    from ..actions.uninstall import Uninstall

    lines(refusing(lambda: Uninstall().perform(go_ahead(yes, dry))) or [], "green")
