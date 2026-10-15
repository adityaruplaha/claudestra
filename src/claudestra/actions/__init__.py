"""The actions, one file each, on the base classes in base.py. Each changing action declares who may
take it; `permissions.matrix()` collects those declarations."""

import importlib
import pkgutil


def load_all() -> None:
    """Import every action module, so each action class is known (for permissions.matrix)."""
    for m in pkgutil.iter_modules(__path__):
        importlib.import_module(f"{__name__}.{m.name}")
