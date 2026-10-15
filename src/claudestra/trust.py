"""trust.yaml and staff.d/ (DESIGN.md §6): who may act on which session.

trust.yaml is the user's, written through `claudestra trust`. The staff files in staff.d/ are claudestra's,
written by `claudestra hire` and changed by rename, move, fix-name and describe; a dismissed staffer's waits in
staff-dismissed.d/. Trust never comes from a staff file except through the folder check in caller.py.
Each is named by its session's full ID.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .claude_fs import UUID
from .portable import atomic_write_text, slug

SCOPES = ("device", "folder")
STAFF = "staff.d"  # a staffer's staff file, <session ID>.yaml, written by claudestra
DISMISSED = "staff-dismissed.d"  # a dismissed staffer's staff file, as it was; rehiring moves it back
STAFF_HEADER = "# Written by `claudestra hire`; claudestra changes it, as rename, move, fix-name and describe do.\n"
CONFIG_ENV = "CLAUDESTRA_CONFIG"  # overrides where the config is; honoured for the user only, as --config is


def config_dir() -> Path:
    """Where trust.yaml and staff.d/ are: $CLAUDESTRA_CONFIG, or $XDG_CONFIG_HOME/claudestra."""
    if p := os.environ.get(CONFIG_ENV):
        return Path(p)
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "claudestra"


def expand(p: str, home: Path) -> Path:
    """A path as written in config, with ~ read as `home` (which may be another machine's)."""
    if p == "~" or p.startswith("~/"):
        p = str(home) + p[1:]
    return Path(os.path.normpath(p))


def tilde(p: str | Path | None, home: Path) -> str:
    """The inverse of expand: a path under `home` written with ~, for config and for display."""
    if p is None:
        return "-"
    s, h = str(p), str(home)
    return "~" + s[len(h) :] if s == h or s.startswith(h + "/") else s


def update_staff_file(sf: StaffFile, change) -> None:
    """Rewrite a staffer's staff file through `change(raw)`, keeping its leading comment lines, atomically."""
    text = sf.file.read_text()
    raw = yaml.safe_load(text) or {}
    change(raw)
    head = "".join(line for line in text.splitlines(keepends=True) if line.startswith("#"))
    atomic_write_text(sf.file, head + yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=100))


def set_staff_name(sf: StaffFile, name: str) -> None:
    """Change only the `name:` line of a staffer's staff file, so its diff is that one line.

    The rest of the file is left as its staffer wrote it. A staff file with no single top-level
    `name:` line on its own is rewritten whole instead, through update_staff_file.
    """
    text = sf.file.read_text()
    lines = text.splitlines(keepends=True)
    at = [i for i, line in enumerate(lines) if line.startswith("name:")]
    if len(at) == 1:
        # JSON's double-quoted string is also YAML's, escapes included.
        lines[at[0]] = f"name: {json.dumps(name, ensure_ascii=False)}\n"
        new = "".join(lines)
        if (yaml.safe_load(new) or {}).get("name") == name:
            atomic_write_text(sf.file, new)
            return
    update_staff_file(sf, lambda raw: raw.__setitem__("name", name))


def set_staff_folder(sf: StaffFile, host: str, folder: Path, home: Path) -> None:
    """Set the staffer's folder for `host` (matched without regard to case) in its staff file."""

    def change(raw: dict) -> None:
        folders = raw.get("folder") or {}
        key = next((h for h in folders if str(h).lower() == host.lower()), host)
        folders[key] = tilde(folder, home)
        raw["folder"] = folders

    update_staff_file(sf, change)


@dataclass
class StaffFile:
    """A staff file as read: what a staffer says about itself, with its folder on this host."""

    file: Path
    name: str
    session: str
    folder: Path | None  # on this host; None if it does not run here
    folders: dict[str, str]  # every host's, as written
    description: str


@dataclass
class MachineConf:
    """A machine as trust.yaml describes it. One with an ssh address accepts connections; one
    without accepts none, and only it can start a transfer with the other."""

    hostname: str
    home: Path
    ssh: str | None
    machine_id: str | None
    autostart: list[str]  # session IDs of this machine's managers, which its login unit starts


@dataclass
class Trust:
    scopes: dict[str, str]  # session ID -> scope
    protected: list[Path]  # this host's protected folders
    protected_raw: dict[str, list[str]]  # every host's, as written
    staff: list[StaffFile]
    machines: dict[str, MachineConf]  # by lower-case hostname
    trust_file: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dismissed: set[str] = field(default_factory=set)  # session IDs with a file in staff-dismissed.d/

    @property
    def config(self) -> Path:
        """The config folder: trust.yaml, staff.d/ and staff-dismissed.d/."""
        return self.trust_file.parent

    def autostart(self, host: str) -> list[str]:
        """The managers trust.yaml says start at login on this machine."""
        m = self.machines.get(host.lower())
        return list(m.autostart) if m else []

    def named(self, name: str) -> StaffFile | None:
        return next((a for a in self.staff if a.name == name), None)

    def staff_file(self, sid: str | None) -> StaffFile | None:
        return next((a for a in self.staff if sid and a.session == sid), None)

    def scope(self, sid: str | None) -> str | None:
        """The session's scope while it is on the staff. A dismissed staffer keeps its scope in
        trust.yaml, so rehiring it brings the scope back, but holds none while dismissed."""
        return self.scopes.get(sid) if sid and self.staff_file(sid) is not None else None

    def device_managers(self) -> list[StaffFile]:
        """The device-scope staffers that run on this host."""
        return [m for m in self.staff if self.scope(m.session) == "device" and m.folder is not None]

    def managed_by(self, sf: StaffFile) -> str:
        """Who the staffer answers to: its folder's managers, or with none, this host's device scope."""
        if self.scope(sf.session) == "device":
            return "the user"
        if self.scope(sf.session) is None and (ms := self.managers_over(sf)):
            return ", ".join(m.name for m in ms)
        ds = [m.name for m in self.device_managers() if m.session != sf.session]
        return (", ".join(ds) + " (device scope)") if ds else "the user (no device-scope manager on this machine)"

    def managers_over(self, sf: StaffFile) -> list[StaffFile]:
        """The folder-scope staffers on this host whose folder holds the staffer's: its managers."""
        return self.managers_of(sf.folder, sf.session) if sf.folder is not None else []

    def managers_of(self, folder: Path, but: str | None = None) -> list[StaffFile]:
        """The folder-scope staffers on this host whose folder holds `folder`, other than session `but`."""
        return [
            m
            for m in self.staff
            if m.session != but
            and self.scope(m.session) == "folder"
            and m.folder is not None
            and folder.is_relative_to(m.folder)
        ]

    def protected_for(self, host: str, home: Path) -> list[Path]:
        """Another machine's protected folders, with ~ read as that machine's home."""
        return next(
            ([expand(f, home) for f in v] for h, v in self.protected_raw.items() if h.lower() == host.lower()), []
        )

    def is_protected(
        self, folder: Path | None = None, slug_name: str | None = None, protected: list[Path] | None = None
    ) -> bool:
        """Whether a session filed at `folder`, or under `slug_name`, is protected (DESIGN.md §6.3).

        Both tests apply whenever both are given: a folder alone could be named to slip past (a
        `--from` that maps to the same slug as a protected folder), and by slug the test errs towards
        protecting more, since slugs are lossy.
        """
        for p in self.protected if protected is None else protected:
            if folder is not None and folder.is_relative_to(p):
                return True
            if slug_name is not None and (slug_name == (ps := slug(p)) or slug_name.startswith(ps + "-")):
                return True
        return False


def _load_yaml(path: Path, label: str, errors: list[str]) -> dict:
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        errors.append(f"{label}: {e}")
        return {}
    if data is None:
        return {}
    if not isinstance(data, dict):
        errors.append(f"{label}: must be a mapping")
        return {}
    return data


def load(host: str, home: Path, config: Path | None = None) -> Trust:
    config = config or config_dir()
    errors: list[str] = []
    warnings: list[str] = []
    trust_file = config / "trust.yaml"
    scopes: dict[str, str] = {}
    protected: list[Path] = []
    protected_raw: dict[str, list[str]] = {}
    machines: dict[str, MachineConf] = {}
    if trust_file.is_file():
        raw = _load_yaml(trust_file, "trust.yaml", errors)
        for sid, entry in (raw.get("sessions") or {}).items():
            scope = entry.get("scope") if isinstance(entry, dict) else None
            if not UUID.match(str(sid)) or scope not in SCOPES:
                errors.append(f"trust.yaml: {sid}: must be a session ID with scope: {' or '.join(SCOPES)}")
                continue
            if set(entry) - {"scope"}:
                errors.append(f"trust.yaml: {sid}: only scope is read; folders come from the session's staff file")
            scopes[str(sid)] = scope
        for h, mc in (raw.get("machines") or {}).items():
            if (
                not isinstance(mc, dict)
                or not isinstance(mc.get("home"), str)
                or not isinstance(mc.get("machine_id"), str)
                or set(mc) - {"home", "machine_id", "ssh", "autostart", "protected"}
            ):
                errors.append(
                    f"trust.yaml: machines: {h}: must have home and machine_id, ssh only if it accepts connections, autostart as a list of session IDs, and protected as a list of folders"
                )
                continue
            autostart = mc.get("autostart") or []
            if not isinstance(autostart, list) or not all(isinstance(x, str) and UUID.match(x) for x in autostart):
                errors.append(f"trust.yaml: machines: {h}: autostart must be a list of session IDs")
                autostart = []
            folders = mc.get("protected") or []
            if not isinstance(folders, list) or not all(isinstance(f, str) for f in folders):
                errors.append(f"trust.yaml: machines: {h}: protected must be a list of folders")
                folders = []
            machines[str(h).lower()] = MachineConf(
                str(h),
                Path(mc["home"]),
                mc.get("ssh") if isinstance(mc.get("ssh"), str) else None,
                mc["machine_id"],
                list(autostart),
            )
            protected_raw[str(h)] = list(folders)
            if str(h).lower() == host.lower():
                protected = [expand(f, home) for f in folders]
        if set(raw) - {"sessions", "machines"}:
            errors.append(f"trust.yaml: unknown keys {sorted(set(raw) - {'sessions', 'machines'})}")
    else:
        warnings.append(f"no {trust_file}: no session may act on another; the user can, from a terminal")

    staff = []
    for f in sorted((config / "staff.d").glob("*.yaml")):
        where = f"staff.d/{f.name}"
        raw = _load_yaml(f, where, errors)
        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{where}: name must be a non-empty string")
            continue
        # A staff file is named by its session's full ID, which is the only place the ID is given.
        if not UUID.match(f.stem):
            errors.append(f"{where}: a staff file is named by its session's full ID, <session ID>.yaml")
            continue
        sid = f.stem
        if "session" in raw:
            errors.append(f"{where}: the session is the file name; drop the session key")
        folders = raw.get("folder") or {}
        if not isinstance(folders, dict) or not all(isinstance(v, str) for v in folders.values()):
            errors.append(f"{where}: folder must map hostnames to paths")
            folders = {}
        folder = next((v for h, v in folders.items() if str(h).lower() == host.lower()), None)
        if "autostart" in raw:
            errors.append(f"{where}: autostart is not a staffer's to set; it is under each machine in trust.yaml")
        desc = raw.get("description")
        if not isinstance(desc, str) or not desc.strip():
            errors.append(f"{where}: description must say what the staffer works on")
            desc = ""
        staff.append(
            StaffFile(
                f,
                name.strip(),
                sid,
                expand(folder, home) if folder else None,
                {str(h): v for h, v in folders.items()},
                desc.strip(),
            )
        )

    for label, values in (("name", [a.name for a in staff]),):
        for v in sorted({v for v in values if values.count(v) > 1}):
            errors.append(f"staff.d/: {label} {v!r} is described by more than one staff file")
    # Only the names of dismissed staff files are read: a scope is the grant of a staffer's authority, so
    # one whose staffer is neither on the staff nor dismissed is an error, and one that is dismissed waits.
    dismissed = {f.stem for f in (config / DISMISSED).glob("*.yaml") if UUID.match(f.stem)}
    on_staff = {a.session for a in staff}
    for sid in sorted(on_staff & dismissed):
        errors.append(f"{DISMISSED}/{sid}.yaml: {sid} is on the staff and dismissed at once")
    for sid, scope in scopes.items():
        if sid not in on_staff and sid not in dismissed:
            errors.append(f"trust.yaml: {sid} has {scope} scope but no staff file; hire it, or revoke the scope")
    return Trust(scopes, protected, protected_raw, staff, machines, trust_file, errors, warnings, dismissed)


def machine_problem(hostname: str, machine_id: str | None, machines: dict[str, MachineConf]) -> str | None:
    """Why this machine is not the one trust.yaml describes under its hostname, if it is not."""
    conf = machines.get(hostname.lower())
    if conf is None:
        return f"{hostname} is not under machines in trust.yaml"
    if conf.machine_id is None:
        return f"trust.yaml gives no machine_id for {hostname}"
    if conf.machine_id != machine_id:
        return f"{hostname}'s derived machine ID is {machine_id}, not the {conf.machine_id} trust.yaml gives"
    return None
