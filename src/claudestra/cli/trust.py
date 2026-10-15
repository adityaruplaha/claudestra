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
from ..claude_fs import UUID
from ..context import Context
from .base import app, refusing
from .ui import Dry, Yes, go_ahead

trust_app = typer.Typer(
    help="trust.yaml: scopes, autostart, protected folders and machines (the user's alone to change)."
)
app.add_typer(trust_app, name="trust")

Session = Annotated[str, typer.Argument(help="The session: a full ID, or a name or 8+ character prefix here.")]
Machine = Annotated[
    str | None, typer.Option("--machine", help="The machine, as trust.yaml names it; default: this one.")
]


class Change(StrEnum):
    add = "add"
    remove = "remove"


def _sid(token: str) -> str:
    """A full session ID as given, or the one session a token names here."""
    return token if UUID.match(token) else refusing(lambda: Context.current().session(token)).id


def _do(action, yes: bool, dry: bool) -> None:
    refusing(lambda: action.perform(go_ahead(yes, dry)))


@trust_app.command("show")
def show() -> None:
    """trust.yaml as claudestra reads it, with each session's current name."""
    print(refusing(TrustShow().perform), end="")


@trust_app.command("grant")
def grant(
    session: Session,
    scope: Annotated[str, typer.Argument(help="device or folder.")],
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Give a session a scope."""
    _do(TrustGrant(_sid(session), scope), yes, dry)


@trust_app.command("revoke")
def revoke(session: Session, dry: Dry = False, yes: Yes = False) -> None:
    """Take a session's scope away."""
    _do(TrustRevoke(_sid(session)), yes, dry)


@trust_app.command("autostart")
def autostart(change: Change, session: Session, machine: Machine = None, dry: Dry = False, yes: Yes = False) -> None:
    """Add a staffer to a machine's login list, or remove it."""
    _do(TrustAutostart(_sid(session), change is Change.add, machine), yes, dry)


@trust_app.command("protect")
def protect(
    change: Change,
    folder: Annotated[Path, typer.Argument(help="The folder; on another machine, as a path there.")],
    machine: Machine = None,
    dry: Dry = False,
    yes: Yes = False,
) -> None:
    """Protect a folder on a machine, so its sessions may not leave it, or stop protecting it."""
    path = folder.expanduser().absolute() if machine is None else folder
    _do(TrustProtect(path, change is Change.add, machine), yes, dry)


@trust_app.command("machine")
def machine(
    change: Change,
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
    _do(TrustMachine(change is Change.add, host, home, machine_id, ssh), yes, dry)
