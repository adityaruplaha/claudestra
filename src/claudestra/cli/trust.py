"""`claudestra trust …`: trust.yaml, changed by command rather than by hand. Every change is the user's alone,
and refused in restricted mode; `trust show` is for anyone."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from ..actions.trust_autostart import TrustAutostart
from ..actions.trust_grant import TrustGrant
from ..actions.trust_machine import TrustMachine
from ..actions.trust_protect import TrustProtect
from ..actions.trust_revoke import TrustRevoke
from ..actions.trust_show import TrustShow
from ..context import Context
from ..trust import SCOPES
from . import select
from .base import app, refusing
from .ui import Dry, Yes, go_ahead

trust_app = typer.Typer(
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
    help="trust.yaml: scopes, autostart, protected folders and machines (the user's alone to change).",
)
app.add_typer(trust_app, name="trust")

STAFFER = select.Staffers()
SCOPED = select.Staffers(scoped=True, help="A staffer with a scope; picked at a terminal.")
SCOPE = select.OneOf({s: "" for s in SCOPES}, "a scope", "Which scope?")
CHANGE = select.OneOf({"add": "", "remove": ""}, "add or remove", "Add or remove?")
PROTECT = select.Folder(help="The folder; on another machine, as a path there. Browsed to at a terminal.")
Session = STAFFER.arg
Machine = Annotated[
    str | None, typer.Option("--machine", help="The machine, as trust.yaml names it; default: this one.")
]


class Change(StrEnum):
    add = "add"
    remove = "remove"


ChangeArg = Annotated[Change | None, typer.Argument(help="add or remove; picked at a terminal.", show_default=False)]


def _change(change: Change | None) -> bool:
    """Whether it adds: as given, or picked at a terminal."""
    return CHANGE.get(change.value if change else None) == "add"


def _do(action, yes: bool, dry: bool) -> None:
    refusing(lambda: action.perform(go_ahead(yes, dry)))


@trust_app.command("show")
def show(ctx: typer.Context) -> None:
    """trust.yaml as claudestra reads it, with each session's current name."""
    print(refusing(TrustShow().perform), end="")


@trust_app.command("grant")
def grant(
    session: Session = None,
    scope: Annotated[
        str | None, typer.Argument(help="device or folder; picked at a terminal.", show_default=False)
    ] = None,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Give a session a scope."""
    sid = STAFFER.get(session)
    scope = SCOPE.get(scope)
    _do(TrustGrant(sid, scope), yes, dry)


@trust_app.command("revoke")
def revoke(session: Session = None, dry: Dry = False, yes: Yes = False) -> None:
    """Take a session's scope away."""
    _do(TrustRevoke(SCOPED.get(session)), yes, dry)


@trust_app.command("autostart")
def autostart(
    change: ChangeArg = None, session: Session = None, machine: Machine = None, dry: Dry = False, yes: Yes = False
) -> None:
    """Add a staffer to a machine's login list, or remove it."""
    add = _change(change)
    _do(
        TrustAutostart(STAFFER.where(on=machine or Context.current().machine.hostname).get(session), add, machine),
        yes,
        dry,
    )


@trust_app.command("protect")
def protect(
    change: ChangeArg = None,
    folder: Annotated[
        Path | None,
        typer.Argument(
            help="The folder; on another machine, as a path there. Asked at a terminal.", show_default=False
        ),
    ] = None,
    machine: Machine = None,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Protect a folder on a machine, so its sessions may not leave it, or stop protecting it."""
    add = _change(change)
    if machine is None:
        path = PROTECT.get(folder)
    else:
        path = folder or Path(select.Text(f"The folder on {machine}:", "the folder").get())
    _do(TrustProtect(path, add, machine), yes, dry)


@trust_app.command("machine")
def machine(
    change: ChangeArg = None,
    host: Annotated[str | None, typer.Argument(help="The machine's hostname; default: this one.")] = None,
    home: Annotated[Path | None, typer.Option("--home", help="Its home folder (another machine only).")] = None,
    machine_id: Annotated[
        str | None, typer.Option("--machine-id", help="Its derived ID, as `trust machine add` prints it there.")
    ] = None,
    ssh: Annotated[str | None, typer.Option("--ssh", help="user@address, if it accepts connections.")] = None,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Describe a machine in trust.yaml, or remove it. This machine's home and ID are worked out here."""
    _do(TrustMachine(_change(change), host, home, machine_id, ssh), yes, dry)
