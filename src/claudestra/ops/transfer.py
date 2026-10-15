"""`claudestra send` and `claudestra fetch`: move a stopped session between the machines (DESIGN.md §8).

The session's stores are staged, their cwd fields rewritten for the destination, copied with
checksums verified on both sides, and only then removed from the source into its trash, so the
session has one home again. A failure part way takes back whatever arrived, on either side. Which
machine may connect to which is DESIGN.md §8; protection and the typed yes for leaving a
laptop are §6.3.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .. import portable
from ..caller import Caller, Refused
from ..claude_fs import KEYED_STORES, UUID, ClaudeFS
from ..model import SessionRecord
from ..trust import MachineConf, Trust, expand, machine_problem, set_staff_folder
from . import rewrite
from . import trash as trash_ops
from .common import (
    Journal,
    log,
    refuse_if_running,
    refuse_link_conflicts,
    remove_tree,
    stores,
)

PACKAGE_DIR = Path(__file__).resolve().parent.parent
STAGING = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / portable.STATE / "staging"


def helper_script() -> str:
    """portable.py's source, then remote_helper.py's: the far side runs the same shared code."""
    return (PACKAGE_DIR / "portable.py").read_text() + "\n\n" + (PACKAGE_DIR / "remote_helper.py").read_text()


class Transport:
    """The other machine: run the helper there, and copy files under its ~/.claude."""

    hostname: str
    home: Path

    def helper(self, req: dict) -> dict:
        raise NotImplementedError

    def push(self, staging: Path, rels: list[str]) -> None:
        raise NotImplementedError

    def pull(self, rels: list[str], staging: Path) -> None:
        raise NotImplementedError


def _parse(out: str, err: str, code: int) -> dict:
    try:
        data = json.loads(out.strip().splitlines()[-1]) if out.strip() else None
    except ValueError:
        data = None
    if code != 0 or not isinstance(data, dict) or "error" in data:
        why = data.get("error") if isinstance(data, dict) else (err.strip() or out.strip())[:300]
        raise Refused(f"on the other machine: {why}")
    return data


class SSHTransport(Transport):
    def __init__(self, conf: MachineConf):
        if not conf.ssh:
            raise Refused(
                f"trust.yaml gives {conf.hostname} no ssh address, so it accepts no connections (DESIGN.md §8)"
            )
        self.hostname, self.home, self.target = conf.hostname, conf.home, conf.ssh

    def helper(self, req: dict) -> dict:
        r = subprocess.run(
            ["ssh", self.target, "python3 - " + shlex.quote(json.dumps(req))],
            input=helper_script(),
            capture_output=True,
            text=True,
            timeout=300,
        )
        return _parse(r.stdout, r.stderr, r.returncode)

    def _rsync(self, src: str, dst: str, rels: list[str]) -> None:
        r = subprocess.run(
            ["rsync", "-a", "--checksum", "--files-from=-", src, dst],
            input="\n".join(rels) + "\n",
            capture_output=True,
            text=True,
            timeout=3600,
        )
        if r.returncode != 0:
            raise Refused(f"rsync failed ({r.returncode}): {r.stderr.strip()[:300]}")

    def push(self, staging: Path, rels: list[str]) -> None:
        self._rsync(f"{staging}/", f"{self.target}:.claude/", rels)

    def pull(self, rels: list[str], staging: Path) -> None:
        self._rsync(f"{self.target}:.claude/", f"{staging}/", rels)


class LocalTransport(Transport):
    """Another home folder on this disk standing in for the other machine (tests)."""

    def __init__(self, hostname: str, home: Path):
        self.hostname, self.home = hostname, home

    def helper(self, req: dict) -> dict:
        r = subprocess.run(
            [sys.executable, "-", json.dumps(req)],
            input=helper_script(),
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "CAM_REMOTE_HOME": str(self.home),
                "XDG_STATE_HOME": str(self.home / ".local" / "state"),
            },
        )
        return _parse(r.stdout, r.stderr, r.returncode)

    def push(self, staging: Path, rels: list[str]) -> None:
        for rel in rels:
            (dst := self.home / ".claude" / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staging / rel, dst)

    def pull(self, rels: list[str], staging: Path) -> None:
        for rel in rels:
            (dst := staging / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.home / ".claude" / rel, dst)


def relabel(rel: str, src_slugs: set[str], dest_slug: str) -> str:
    """A store's path under ~/.claude on the destination: projects/<any source slug>/… moves to the
    destination folder's slug; the keyed stores keep their place."""
    parts = Path(rel).parts
    return str(Path("projects", dest_slug, *parts[2:])) if parts[0] == "projects" and parts[1] in src_slugs else rel


def store_roots(rels) -> list[str]:
    """The stores a set of files belongs to: projects/<slug>/<entry> or <store>/<key>."""
    return sorted({str(Path(*Path(r).parts[: 3 if r.startswith("projects/") else 2])) for r in rels})


@dataclass
class TransferPlan:
    direction: str  # "send" or "fetch"
    session_id: str
    name: str | None
    src_folder: str
    dest_folder: str
    remote: str
    files: dict[str, str] = field(default_factory=dict)  # source rel -> destination rel
    cwd_changes: dict[str, int] = field(default_factory=dict)

    def describe(self) -> list[str]:
        here, there = (
            (self.src_folder, f"{self.remote}:{self.dest_folder}")
            if self.direction == "send"
            else (f"{self.remote}:{self.src_folder}", self.dest_folder)
        )
        out = [
            f"{self.direction} {self.session_id} ({self.name or '-'}): {here} -> {there}",
            f"  {len(self.files)} files",
        ]
        return out + [f"  cwd  {n} x {k}" for k, n in sorted(self.cwd_changes.items(), key=lambda kv: -kv[1])]


def _check_remote(probe: dict, t: Transport, machines: dict[str, MachineConf]) -> None:
    """The far side must be the machine trust.yaml describes, by hostname and derived machine ID."""
    if str(probe.get("hostname", "")).lower() != t.hostname.lower():
        raise Refused(f"expected {t.hostname} on the far side, found {probe.get('hostname')}")
    if why := machine_problem(probe["hostname"], probe.get("machine_id"), machines):
        raise Refused(f"on the far side: {why}")


def _check_reachable(t: Transport, machines: dict[str, MachineConf]) -> None:
    far = machines.get(t.hostname.lower())
    if far is None or not far.ssh:
        raise Refused(f"{t.hostname} accepts no connections (DESIGN.md §8); run this on {t.hostname} instead")


def _rewrite_staged(staging: Path, rels, sid: str, mapped: Callable[[str], str | None]) -> dict[str, int]:
    changes: dict[str, int] = {}
    for rel in rels:
        p = staging / rel
        if p.suffix == ".jsonl" and (p.stem == sid or p.parent.name == "subagents"):
            for k, n in rewrite.rewrite_file(p, mapped, None).items():
                changes[k] = changes.get(k, 0) + n
    return changes


def send(
    fs: ClaudeFS,
    host: str,
    machines: dict[str, MachineConf],
    trust: Trust,
    caller: Caller,
    s: SessionRecord,
    t: Transport,
    dest_folder: str | None,
    src_folder: Path | None,
    dry: bool,
    confirm: Callable[[str], bool],
) -> TransferPlan:
    _check_reachable(t, machines)
    refuse_if_running(fs, s)
    if len(s.homes) != 1:
        raise Refused(f"{s.session_id} is filed under {len(s.homes)} slugs; settle that first")
    src = src_folder or s.folder
    if src is None or fs.filed_slug(src) != s.homes[0]:
        raise Refused(f"the folder {s.homes[0]} stands for is not known; give it with --from")
    if trust.is_protected(src, s.homes[0]):
        raise Refused(
            f"{s.session_id} is in a protected folder on {host}, and protection stops it moving out (DESIGN.md §6.3)"
        )
    dest_raw = dest_folder or (
        next((v for h, v in s.staff_file.folders.items() if h.lower() == t.hostname.lower()), None)
        if s.staff_file
        else None
    )
    if not dest_raw:
        raise Refused(f"no folder on {t.hostname}: its staff file gives none, so give one with --to")
    dest = str(expand(dest_raw, t.home))
    if not dest.startswith("/"):
        raise Refused(f"--to {dest_raw} is not an absolute path on {t.hostname}")
    if why := portable.slug_problem(dest):
        raise Refused(why)

    meta = fs.read_meta(fs.transcript(s.homes[0], s.session_id), s.session_id)
    st = stores(fs, s, meta.secondary_ids)
    refuse_link_conflicts(fs, st.paths())
    src_slugs = {Path(label).parts[1] for label, _ in st.items if label.startswith("projects/")}
    rels = [
        str(f.relative_to(fs.root))
        for p in st.paths()
        for f in ([p] if p.is_file() else sorted(q for q in p.rglob("*") if q.is_file()))
    ]
    cwds = {c for rel in rels if rel.endswith(".jsonl") for c in rewrite.count(fs.root / rel, lambda c: c)}
    pairs = [(str(src), dest), (str(fs.home), str(t.home))]
    candidates = {c for c in (rewrite.mapper(pairs, lambda _c: True)(x) for x in cwds) if c}
    probe = t.helper(
        {
            "action": "probe",
            "sid": s.session_id,
            "keyed": list(KEYED_STORES),
            "secondary": sorted(meta.secondary_ids),
            "dirs": sorted(candidates | {dest}),
            "filed": [dest],
        }
    )
    _check_remote(probe, t, machines)
    if probe["running"]:
        raise Refused(f"{s.session_id} is running on {t.hostname} (pid {probe['running']})")
    if probe["stores"]:
        raise Refused(f"{t.hostname} already holds {', '.join(probe['stores'][:3])}; a second copy would be a fork")
    if not probe["dirs"].get(dest):
        raise Refused(f"{dest} does not exist on {t.hostname}")
    # Filed where the far side's Claude Code files a session started in dest, redirects followed.
    plan = TransferPlan("send", s.session_id, s.name, str(src), dest, t.hostname)
    plan.files = {rel: relabel(rel, src_slugs, probe["filed"][dest]) for rel in rels}
    if len(set(plan.files.values())) != len(plan.files):
        raise Refused(
            "two of the session's files would land on the same path; it is split across slugs with overlapping files"
        )
    mapped = rewrite.mapper(pairs, lambda c: bool(probe["dirs"].get(c)))
    for rel in rels:
        if rel.endswith(".jsonl"):
            for k, n in rewrite.count(fs.root / rel, mapped).items():
                plan.cwd_changes[k] = plan.cwd_changes.get(k, 0) + n
    if dry:
        return plan
    if not confirm(s.session_id):
        raise Refused("the user did not confirm sending this session off this machine")

    staging = STAGING / f"{portable.stamp()}-{s.session_id}"
    pushed = False
    try:
        for rel, dst in plan.files.items():
            (staging / dst).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fs.root / rel, staging / dst)
        _rewrite_staged(staging, plan.files.values(), s.session_id, mapped)
        want = {dst: portable.sha256(staging / dst) for dst in plan.files.values()}
        pushed = True
        t.push(staging, list(want))
        got = t.helper({"action": "sha", "files": list(want)})
        if bad := [r for r, h in want.items() if got.get(r) != h]:
            raise Refused(f"{len(bad)} files did not arrive intact (first: {bad[0]})")
        refuse_if_running(fs, s)  # again, just before the copy here goes
        trash_ops.apply(fs, caller, trash_ops.Plan(s, st.items, 0), reason=f"sent to {t.hostname}")
    except Exception as e:
        if pushed:  # whatever arrived goes to the far side's trash, so there is one home again
            try:
                t.helper(
                    {
                        "action": "trash",
                        "sid": s.session_id,
                        "stores": store_roots(plan.files.values()),
                        "reason": "failed send",
                    }
                )
                after = "the copy there was moved to its trash"
            except Refused as err:
                after = (
                    f"and the copy there could NOT be trashed ({err}): it now has two homes; trash it on {t.hostname}"
                )
        else:
            after = "nothing reached the other machine"
        log(caller, "send-failed", s.session_id, f"{e}; {after}")
        raise Refused(f"the send failed ({e}); {after}, and nothing here changed") from e
    finally:
        if staging.exists():
            remove_tree(staging)
    if s.staff_file and dest_folder:
        set_staff_folder(s.staff_file, t.hostname, Path(dest), t.home)
    entry = {
        "action": "send",
        "session": s.session_id,
        "from": f"{host}:{src}",
        "to": f"{t.hostname}:{dest}",
        "files": len(plan.files),
    }
    log(caller, "send", s.session_id, json.dumps(entry))
    t.helper({"action": "log", "entry": {**entry, "caller": caller.describe()}})
    return plan


def fetch(
    fs: ClaudeFS,
    host: str,
    machines: dict[str, MachineConf],
    trust: Trust,
    caller: Caller,
    sid: str,
    t: Transport,
    src_folder: str | None,
    dest_folder: Path | None,
    staff_folders: dict[str, str],
    dry: bool,
) -> TransferPlan:
    if not UUID.match(sid):
        raise Refused(f"{sid!r} is not a full session ID")
    _check_reachable(t, machines)
    if list(fs.projects.glob(f"*/{sid}.jsonl")) or any((fs.root / s / sid).exists() for s in KEYED_STORES):
        raise Refused(f"{sid} already has files on {host}; a second copy would be a fork")
    folder_for = {h.lower(): v for h, v in staff_folders.items()}
    src_raw = src_folder or folder_for.get(t.hostname.lower())
    src = str(expand(src_raw, t.home)) if src_raw else None
    probe = t.helper(
        {
            "action": "probe",
            "sid": sid,
            "keyed": list(KEYED_STORES),
            "filed": [src] if src and src.startswith("/") else [],
        }
    )
    _check_remote(probe, t, machines)
    if probe["running"]:
        raise Refused(f"{sid} is running on {t.hostname} (pid {probe['running']}); stop it first")
    homes = sorted(
        {
            Path(r).parts[1]
            for r in probe["stores"]
            if r.startswith("projects/") and r.endswith(".jsonl") and Path(r).stem == sid
        }
    )
    if len(homes) != 1:
        raise Refused(f"{sid} has {len(homes)} transcripts on {t.hostname}")
    if not src or probe["filed"].get(src) != homes[0]:
        raise Refused(f"the folder {homes[0]} stands for on {t.hostname} is not known; give it with --from")
    if trust.is_protected(Path(src), homes[0], trust.protected_for(t.hostname, t.home)):
        raise Refused(
            f"{sid} is in a protected folder on {t.hostname}, and protection stops it moving out (DESIGN.md §6.3)"
        )
    dest = dest_folder or (expand(folder_for[host.lower()], fs.home) if host.lower() in folder_for else None)
    if dest is None or not dest.is_dir():
        raise Refused(f"no folder on {host} for it: give an existing one with --to")
    got = t.helper({"action": "list", "stores": probe["stores"]})
    if got.get("links"):
        raise Refused(
            f"on {t.hostname}, the session's stores hold symlinks ({', '.join(got['links'][:3])}); settle which session owns those files there first"
        )
    listing = got["files"]
    src_slugs = {Path(r).parts[1] for r in probe["stores"] if r.startswith("projects/")}
    plan = TransferPlan("fetch", sid, None, src, str(dest), t.hostname)
    plan.files = {r: relabel(r, src_slugs, fs.filed_slug(dest)) for r in listing}
    if len(set(plan.files.values())) != len(plan.files):
        raise Refused("two of the session's files would land on the same path")
    if clash := [d for d in plan.files.values() if (fs.root / d).exists()]:
        raise Refused(f"{fs.root / clash[0]} already exists")
    if dry:
        return plan

    staging = STAGING / f"{portable.stamp()}-{sid}"
    journal = Journal()
    try:
        t.pull(listing, staging / "in")
        want = t.helper({"action": "sha", "files": listing})
        if bad := [r for r in listing if portable.sha256(staging / "in" / r) != want.get(r)]:
            raise Refused(f"{len(bad)} files did not arrive intact (first: {bad[0]})")
        for r, d in plan.files.items():
            portable.move_into(staging / "in" / r, staging / "out" / d)
        plan.cwd_changes = _rewrite_staged(
            staging / "out", plan.files.values(), sid, rewrite.mapper([(src, str(dest)), (str(t.home), str(fs.home))])
        )
        for d in plan.files.values():
            journal.move(staging / "out" / d, fs.root / d)
        t.helper(
            {"action": "trash", "sid": sid, "stores": probe["stores"], "slug": homes[0], "reason": f"fetched by {host}"}
        )
    except Exception as e:
        stuck = journal.undo()  # the copy here goes again, so the session stays where it was
        log(caller, "fetch-failed", sid, f"{e}" + (f"; could not take back {stuck}" if stuck else ""))
        raise Refused(
            f"the fetch failed ({e}); nothing changed on either machine"
            + (f", except that these could not be taken back here: {'; '.join(stuck)}" if stuck else "")
        ) from e
    finally:
        if staging.exists():
            remove_tree(staging)
    entry = {
        "action": "fetch",
        "session": sid,
        "from": f"{t.hostname}:{src}",
        "to": f"{host}:{dest}",
        "files": len(plan.files),
    }
    log(caller, "fetch", sid, json.dumps(entry))
    t.helper({"action": "log", "entry": {**entry, "caller": caller.describe()}})
    return plan
