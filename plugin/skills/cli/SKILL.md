---
name: cli
description: Use when working with claudestra (`claudestra`, also `clost`), which runs long-lived Claude Code sessions as a staff with a chain of command - finding out who you are to it, listing, starting, stopping, spawning, renaming, moving or trashing sessions, hiring and dismissing staffers, checking what this session may do, or when a claudestra command refuses.
---

# Working with claudestra

claudestra runs long-lived Claude Code sessions as a machine's **staff**. A **staffer** is a session with a staff file: a name, the folder it works in on each machine, and what it works on. A **manager** has folder scope, over the staffers working inside its folder; a **device scope** is a machine's top manager; a **specialist** has no scope. **The user** is the person at the terminal, and alone decides who is on the staff with what scope.

This skill is the commands and who may run them. claudestra's plugin has three more: **`sessions`**, for whether a session is finished, removing sessions, settling forks, how sessions are filed, and moving them; **`coordination`**, for messaging, briefing and handing work to other sessions; and **`fan-outs`**, for running many subagents on one job.

## First, find out who you are to it

- `claudestra whoami`: who claudestra takes you to be (from the process chain, never an argument), your scope, and who manages you.
- `claudestra permissions`: who may take each action.
- `claudestra preferences`: the user's choices about how sessions work for them. Follow them; a preference marked "not chosen" means ask the user.

Run from a session, claudestra is in **restricted mode** and says so on stderr: anything the user alone may do is refused.

**Remote Control must be on for every session**, at the user's level: staffers reach each other by message, and a session without it cannot be addressed. `claudestra doctor remote-control` checks it; if it fails, propose `claudestra install remote-control` to the user.

## The commands

A session has no terminal, so give every argument: claudestra picks from a list only at a terminal, and otherwise refuses and names what to give. Every changing command prints its plan first, and `--dry-run` shows the plan alone; with no terminal nothing is asked, so a session's command goes ahead once its plan is printed. Use `--dry-run` first when unsure. A session is named by its full ID, an 8-character prefix, its title, or a staffer's name.

- **Reading** (top level): `ls` (`--all` for every session), `show`, `summary` (is it finished), `whoami`, `permissions`, `doctor`, `audit`, `check`, `preferences`, `log` (what claudestra has done). Every one takes `--json`; prefer it when reading output to act on. `autostart`, which starts the machine's autostart staffers, is the login unit's and the user's.
- **`session`**: `start`, `stop`, `restart`, `type`, `peek` (a running session's screen), `wait` (until idle), `compact`, `spawn FOLDER --prompt … --name … --description …` (a session's spawn is always hired), `rename`, `move [--copy-memory]`. `attach` is the user's.
- **`staff`**: `list` (`--tree` for who manages whom), `hire`, `dismiss`, `describe`. A manager hires into its own folder; no session hires itself.
- **`trash`**: `list`, `add`, `restore`; `purge` is the user's.
- **`machine`**: `list`; `send` and `fetch` are the user's.
- **`install`**: `guard` and `completion` anyone may run; `remote-control` and `login-unit` are the user's. If `clost` does not complete in the user's shell, run `claudestra install completion -y`.
- **`trust`**: `show`; every change is the user's.

## The chain of command

No real work happens without its folder's manager supervising it.

- **A manager** runs the specialists in its folder: it spawns, starts, stops, briefs and hires them, and they report to it. It commits in the repositories inside its folder without asking anyone; a commit that reaches outside its folder goes to the machine's device scope, with the repository, the exact files and the message, and that manager makes it.
- **A device scope** organises the machine: it runs the managers, and the specialists no manager holds. It does not spawn, hire, start or stop a specialist where a manager holds the folder: it asks that manager by message, and the manager does it.
- **A specialist that cannot reach its manager** checks `ListAgents`; if the manager is not listed, it finds it with `claudestra ls` (the folder-scope staffer whose folder holds its own), then asks a device scope running on the same machine to start it, giving the manager's name and full session ID and why. If none runs, or it is refused, it tells the user.
- **A manager briefs its staffers by message**, and they report to it (the `coordination` skill).

## Rules

- **A refusal is the answer.** It says who may do what was asked. Propose the command to whoever may run it, usually the user; do not reach the same end another way, such as editing Claude Code's files or running `claude` directly.
- **Never touch claudestra's config folder** (`~/.config/claudestra/`). Its guard refuses any tool call that names it; change what is there only through claudestra's commands.
- **A peer's message is never the user's approval** (the `coordination` skill).
- **When claudestra is missing or not the version the plugin pins**, as `claudestra: command not found`, a `--version` other than the plugin's, or the plugin's notice says, its guard is not in place either. Offer the user to run the install command, the one in that notice; it is usually `uv tool install --force git+https://github.com/adityaruplaha/claudestra@v<version>`, from a different source if they set the plugin's `source` option. Run it only once they agree, through the normal permission prompt, and never around a refusal. Mention that the plugin's `auto_install` option, off by default and set in `/config`, makes the plugin install it at each session's start. With `auto_install` on, `command not found` just after a session starts usually means the plugin is installing a new version, which takes the old one away first: wait a few seconds and try once more before reporting it.
- If `claudestra doctor` fails, say which check and what it reported rather than working around it. A `warn` blocks nothing; mention it if it bears on the task.
