---
name: claudestra
description: Use when working with claudestra, the CLI that runs long-lived Claude Code sessions as a staff (staffers, managers, specialists) - listing, starting, stopping, renaming, moving, hiring or dismissing sessions, checking what this session may do, or when a claudestra command refuses.
---

# Working with claudestra

claudestra runs long-lived Claude Code sessions as a **staff**. A **staffer** is a session with a staff file: a name, the folder it works in on each machine, and a description of what it works on. A **manager** is a staffer with folder scope, answerable for the staffers working under its folder; a **specialist** has no scope; a **device scope** looks after a whole machine. **The user** is the person at the terminal, and alone decides who is on the staff with what scope.

## First, find out who you are to it

- `claudestra whoami`: who claudestra takes you to be (it reads the process chain, never an argument), your scope, and who manages you.
- `claudestra permissions`: who may take each action. On a session, it depends on your relation to that session; otherwise, on what kind of caller you are.

**Remote Control must be on for every session**, set at the user's level (`remoteControlAtStartup` in `~/.claude/settings.json`): staffers reach each other by message, and a session without it cannot be addressed. `claudestra doctor remote-control` checks it; if it fails, propose `claudestra enable-remote-control` to the user, which is theirs to run.

Run from a session, claudestra is in **restricted mode** and says so on stderr: anything the user alone may do is refused.

## Reading

`claudestra ls` (staffers and running sessions; `--all` for every session), `show <session>`, `summary <session>` (is it finished: its typed prompts, what was relayed, its last reply), `audit`, `check`, `doctor`. A session is named by its full ID, an 8-character prefix, its title, or a staffer's name.

## Changing

Every changing command prints its plan first. Use `--dry-run` to see the plan alone, and `-y` to go ahead without the prompt, which a session needs since it has no terminal to answer from.

- `start`, `stop`, `restart`, `type`, `compact`: running sessions in claudestra's tmux.
- `hire`, `dismiss`, `describe`: the staff. A manager hires into its own folder; no session hires itself.
- `rename`, `move`, `trash`, `restore`: a session's name and where it is filed.

## Rules

- **A refusal is the answer.** It says who may do what was asked. Propose the command to whoever may run it (usually the user); do not reach the same end another way, such as editing Claude Code's files or running `claude` directly.
- **Never touch claudestra's config folder** (`~/.config/claudestra/`: `trust.yaml`, `staff.d/`). claudestra's guard refuses any tool call that names it, and the way to change what is there is claudestra's commands: `hire`, `dismiss`, `describe`, and `trust`, which is the user's.
- **The user's alone**: `trust`, `purge`, `send`, `fetch`, `attach`, `enable-remote-control`, and installing the login unit. Propose these; do not try them.
- If `claudestra doctor` fails, say which check and what it reported rather than working around it.
