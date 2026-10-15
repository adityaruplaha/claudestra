"""`claudestra move`: refile a stopped session under another folder on this machine.

What moves and why is in DESIGN.md §9. The cwd fields are rewritten first, in place and backed up, and
the files are moved after; a failure anywhere puts every move back and restores the backups, so a move
either happens whole or not at all.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .. import portable
from ..caller import Caller, Refused
from ..claude_fs import ClaudeFS
from ..model import SessionRecord
from ..portable import atomic_write_text
from ..trust import StaffFile, Trust, set_staff_folder, tilde
from . import rewrite
from .common import (
    Journal,
    backup_dir,
    guard,
    log,
    refuse_if_running,
    refuse_link_conflicts,
)


@dataclass
class MovePlan:
    session: SessionRecord
    src_folder: Path
    dest_folder: Path
    dest_slug: str
    exact: bool = False
    moves: list[tuple[Path, Path]] = field(default_factory=list)  # files and whole folders
    merges: list[tuple[Path, Path]] = field(default_factory=list)  # an <id>/ folder into an existing one
    cwd_changes: dict[str, int] = field(default_factory=dict)
    job_states: list[Path] = field(default_factory=list)
    staff_file: StaffFile | None = None

    def mapper(self):
        return rewrite.mapper([(str(self.src_folder), str(self.dest_folder))], exact=self.exact)

    def describe(self, home: Path) -> list[str]:
        out = [f"move {self.session.session_id} from {tilde(self.src_folder, home)} to {tilde(self.dest_folder, home)}"]
        out += [f"  move   {tilde(a, home)} -> {tilde(b, home)}" for a, b in self.moves]
        out += [f"  merge  {tilde(a, home)} into {tilde(b, home)}" for a, b in self.merges]
        out += [f"  cwd    {n} x {tilde(k, home)}" for k, n in sorted(self.cwd_changes.items(), key=lambda kv: -kv[1])]
        out += [f"  job    {tilde(p, home)}: cwd and transcript path" for p in self.job_states]
        if self.staff_file:
            out.append(f"  staff file {self.staff_file.file.name}: folder for this host")
        return out


def plan(
    fs: ClaudeFS, host: str, trust: Trust, s: SessionRecord, dest: Path, src: Path | None, exact: bool = False
) -> MovePlan:
    """Everything a move will do, refusing what cannot be done. Who may is the action's to decide."""
    refuse_if_running(fs, s)
    if len(s.homes) != 1:
        raise Refused(f"{s.session_id} is filed under {len(s.homes)} slugs ({', '.join(s.homes)}); settle that first")
    src_folder = src or s.folder
    if src_folder is None:
        raise Refused(
            f"the folder {s.homes[0]} stands for is not known (several folders map to it, or none); give it with --from"
        )
    if fs.filed_slug(src_folder) != s.homes[0]:
        raise Refused(f"--from {src_folder} does not map to {s.homes[0]}")
    dest = Path(os.path.normpath(dest))
    if not dest.is_dir():
        raise Refused(f"{dest} does not exist")
    if trust.is_protected(src_folder, s.homes[0]) and not any(
        dest.is_relative_to(p) and src_folder.is_relative_to(p) for p in trust.protected
    ):
        raise Refused(f"{s.session_id} is in a protected folder and {dest} is outside it (DESIGN.md §6.3)")
    if why := portable.slug_problem(dest):
        raise Refused(why)
    dest_slug = fs.filed_slug(dest)  # where Claude Code files a session started there, redirects followed
    if dest_slug == s.homes[0]:
        raise Refused(f"{s.session_id} is already filed under {dest_slug}")

    plan = MovePlan(s, src_folder, dest, dest_slug, exact)
    sid, src_dir, dst_dir = s.session_id, fs.projects / s.homes[0], fs.projects / dest_slug
    if (fs.transcript(dest_slug, sid)).exists():
        raise Refused(f"{fs.transcript(dest_slug, sid)} already exists")
    plan.moves.append((fs.transcript(s.homes[0], sid), fs.transcript(dest_slug, sid)))
    plan.moves += [
        (f, dst_dir / f.name) for slug_name, f, other in fs.set_aside() if other == sid and slug_name == s.homes[0]
    ]
    # Every <id>/ folder, under any slug: a session that changed directory left tool results under
    # the other slug, and they all belong with the transcript now.
    target = dst_dir / sid
    for d in sorted(fs.projects.glob(f"*/{sid}")):
        if d == target or not d.is_dir():
            continue
        if target.exists() or any(b == target for _, b in plan.moves):
            a = {p.relative_to(d) for p in d.rglob("*") if p.is_file()}
            b = {p.relative_to(target) for p in target.rglob("*") if p.is_file()} if target.exists() else set()
            b |= {p.relative_to(src) for src, dst in plan.moves if dst == target for p in src.rglob("*") if p.is_file()}
            if clash := sorted(a & b):
                raise Refused(
                    f"{d} and {target} both hold {clash[0]}" + (f" and {len(clash) - 1} more" if len(clash) > 1 else "")
                )
            plan.merges.append((d, target))
        else:
            plan.moves.append((d, target))
    for a, b in plan.moves + plan.merges:
        guard(fs, a)
        guard(fs, b)
    refuse_link_conflicts(fs, [a for a, _ in plan.moves + plan.merges])

    for f in rewrite.session_files(src_dir / sid, fs.transcript(s.homes[0], sid)):
        for k, n in rewrite.count(f, plan.mapper()).items():
            plan.cwd_changes[k] = plan.cwd_changes.get(k, 0) + n
    plan.job_states = [j.folder / "state.json" for j in s.jobs if (j.folder / "state.json").is_file()]
    plan.staff_file = s.staff_file
    return plan


def apply(fs: ClaudeFS, host: str, caller: Caller, plan: MovePlan) -> None:
    s, sid = plan.session, plan.session.session_id
    refuse_if_running(fs, s)  # again: the user may have resumed it while the plan was shown
    backup = backup_dir("move", sid)
    mapped = plan.mapper()
    src_dir = fs.projects / s.homes[0]
    rewritten: list[tuple[Path, Path]] = []  # (file, its backup)
    journal = Journal()
    try:
        for f in rewrite.session_files(src_dir / sid, fs.transcript(s.homes[0], sid)):
            keep = backup / f.relative_to(src_dir).parent
            if rewrite.rewrite_file(f, mapped, keep):
                rewritten.append((f, keep / f.name))
        for a, b in plan.moves:
            journal.move(a, b)
        for a, b in plan.merges:
            for f in sorted((p for p in a.rglob("*") if p.is_file() or p.is_symlink()), key=str):
                journal.move(f, b / f.relative_to(a))
        for p in plan.job_states:
            raw = json.loads(p.read_text())
            backup.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, backup / f"job-{p.parent.name}-state.json")
            if isinstance(raw.get("cwd"), str):
                raw["cwd"] = mapped(raw["cwd"]) or raw["cwd"]
            if isinstance(raw.get("linkScanPath"), str) and raw["linkScanPath"].endswith(f"/{sid}.jsonl"):
                raw["linkScanPath"] = str(fs.transcript(plan.dest_slug, sid))
            atomic_write_text(p, json.dumps(raw))
        if plan.staff_file:
            set_staff_folder(plan.staff_file, host, plan.dest_folder, fs.home)
    except Exception as e:
        stuck = journal.undo()
        for f, copy in rewritten:
            try:
                shutil.copy2(copy, f)
            except OSError as err:
                stuck.append(f"restore {f}: {err}")
        for p in plan.job_states:
            if (copy := backup / f"job-{p.parent.name}-state.json").exists():
                shutil.copy2(copy, p)
        log(caller, "move-failed", sid, f"{e}; undone" + (f", except {stuck}" if stuck else ""))
        raise Refused(
            f"the move failed ({e}); everything was put back"
            + (f", except: {'; '.join(stuck)}" if stuck else "")
            + f". Backups are in {backup}"
        ) from e
    for a, _ in plan.merges:  # the emptied folders, only once nothing can need them back
        for d in sorted((p for p in a.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            d.rmdir()
        a.rmdir()
    log(caller, "move", sid, f"{s.homes[0]} -> {plan.dest_slug}; backups in {backup}")
