"""claudestra's command line. Importing the command modules registers them on `app`, in this order, which
is the order `claudestra --help` and the menu list them in."""

# isort: off
from . import read, staff, sessions, machines, trust, setup  # noqa: F401
from .base import app

# isort: on

__all__ = ["app"]
