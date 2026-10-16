---
name: sessions
description: Use when judging whether a Claude Code session is finished, removing or cleaning up sessions, finding and settling forked or duplicate sessions, working out where a session is filed (including multi-root VS Code workspaces), or moving a session to another folder or machine.
---

# Sessions on disk

Whether a session is finished, removing it, settling forks, how Claude Code files sessions, and moving them. What claudestra reads on disk, and relies on, is its `DESIGN.md` §3, checked by `claudestra doctor`.

## Is a session finished?

`claudestra summary SESSION` shows the prompts the user typed, a count of what other sessions relayed, its subagents and compactions, and its last reply, which is usually where a session says what is done and what is left. Check that against where it worked: a merged or pushed branch, a clean tree, a deliverable that went out. Only the user knows whether the work is done, so **ask which items are complete**. Open items in its last reply go into the project's own docs before the session is removed, or they are lost with it; so does any convention or correction from it that should outlive it.

**Whether a finished session's conversation is kept** is the user's choice: `claudestra preferences` shows `finished-transcripts`. With `disposable`, offer to trash a session once its work has gone out, without raising the loss of its history; with `keep`, propose removing a session only when asked; unchosen or `ask`, ask.

## Removing sessions

Claude Code has no command to delete one session: `cleanupPeriodDays` deletes by age, and `claude project purge` removes a whole project, its auto-memory with it. So `claudestra trash add` moves a session and every store keyed by it to a trash, `claudestra trash restore` puts it back exactly, and only `claudestra trash purge`, the user's, deletes.

`trash add` refuses a session that is open, even idle, or written in the last few minutes: an open session that has been moved writes a small stub back to its old place when it exits, which then shows up as a duplicate. After a trash, `claudestra audit` shows such a stub if one appears.

## Forks

A fork is a session whose transcript begins with a copy of another's: `--fork-session`, a resume that branched, or the same session resumed in two places at once. Copies share record `uuid`s. `claudestra audit forks` groups them and counts, for each copy, the records no other copy has (**own**) and the prompts among them the user typed (**own prompts**).

- **No own prompts:** the copy is contained in the others and is redundant.
- **Own prompts that only coordinate or stand down:** a side branch that yielded to another copy, also redundant. Read its tail anyway: a finding left unacted on there goes to the owning docs or to the user first.
- **Own prompts with real work:** each copy holds history the others lack; whether to keep them depends on whether that work is finished, so ask.

The check is per machine, since transcripts are not synced.

**Linked subagent transcripts.** A session continued into a new one may reach some of its subagents' transcripts through symlinks into the old one, so two sessions share a file; `trash add`, `move` and `send` refuse either until the user decides which owns it (`claudestra audit links`). Check with `lstat` (`ls -l`, `test -L`) before calling two files copies: followed through a link, they look identical.

## How sessions are filed

A session is filed under the slug of the folder it was started in. For a multi-root VS Code workspace, Claude Code files every session under the **first folder listed in the workspace file**, whichever folder the work concerns, and auto-memory follows the same path. So do not infer from a slug which repository a session was about, and look in the workspace's first-folder slug before concluding that a session or a memory is missing. Each other folder's slug holds a `.session-aliases` file naming the first folder's: such a slug folder holds no sessions and is not left over, so never trash it as empty.

## Moving a session

**A moved session reads as if it had always been there.** `claudestra session move` carries every store with the session, merges a split session's folders, and changes only the `cwd` fields, so Claude Code's session list shows the folder it now lives in; messages and tool output keep the paths as they were said. `--exact` rewrites only the launch folder itself, for a session that also worked in that folder's subfolders. When a project folder is renamed or moved, move its sessions after it. `claudestra machine send` and `fetch`, the user's, do the same between machines.
