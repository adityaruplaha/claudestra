# claudestra

claudestra runs long-lived Claude Code sessions as a machine's **staff**, on one machine or several, with a chain of command. It keeps track of every session, starts and stops sessions in a tmux session of its own with Remote Control on, lets sessions manage other sessions within limits you set, moves sessions between folders and between machines, finds forks, orphans and stale state, and removes sessions to a trash rather than deleting them.

The command is `claudestra`, also installed as `clost`. How it is built, and why, is in [DESIGN.md](DESIGN.md).

## Requirements

- Linux, with tmux and [uv](https://docs.astral.sh/uv/).
- Claude Code, with **Remote Control on for every session**. Sessions coordinate by messaging each other, and a session without Remote Control cannot be addressed. `claudestra setup` turns it on.
- systemd, if staffers are to start at login.

## Installing

claudestra ships as a Claude Code plugin. This repository is its own marketplace:

```
/plugin marketplace add adityaruplaha/claudestra
/plugin install claudestra@claudestra
```

When a session starts, the plugin installs the claudestra version it pins with `uv tool install`, puts claudestra's guard in place (deny rules and a hook that keep sessions out of its config), and installs shell completion. Without the plugin, install the CLI yourself:

```
uv tool install git+https://github.com/adityaruplaha/claudestra@v0.2.0
```

Then, in a terminal:

```
clost setup
```

`setup` walks through each step not yet done, showing what it will do and asking first: this machine in `trust.yaml`, the guard, Remote Control, a device-scope manager that starts at login, the login unit, shell completion, and your preferences. Run it again at any time; it skips what is done.

## The staff

- A **session** is any Claude Code session.
- A **staffer** is a session on the staff: it has a staff file giving its name, the folder it works in on each machine, and what it works on.
- A **manager** is a staffer with **folder scope**: it runs the staffers whose folders lie inside its own.
- A **device scope** is a machine's top manager, under you: it organises the machine's sessions and runs what no folder manager holds.
- A **specialist** is a staffer with no scope.

You alone decide who is on the staff with what scope (`clost trust`). claudestra works out who is calling from the process chain, never from an argument, so a session cannot claim to be someone else, and when any Claude process is in the chain it refuses whatever is yours alone. `clost whoami` says who claudestra takes you to be, and `clost permissions` who may do what.

## Commands

Every argument that names a session, staffer, trash entry, machine, folder or choice can be given on the command line, or left out at a terminal and picked from a list. Without a terminal, as when a session runs claudestra, it must be given. Every changing command prints its plan first; `--dry-run` (`-n`) stops there, and `--yes` (`-y`) skips the question. A bare group shows its help. Bare `clost` at a terminal opens a menu of every command.

**Reading**

| Command | |
| :--- | :--- |
| `clost ls` | Staffers and running sessions; `--all` for every session. |
| `clost show SESSION` | One session in full. |
| `clost summary SESSION` | Whether a session is finished: the prompts you typed, what other sessions relayed, its last reply. |
| `clost whoami` | Who claudestra takes you to be, your scope, and who manages you. |
| `clost permissions` | Who may take each action. |
| `clost doctor` | Checks every fact about Claude Code's files that claudestra relies on, and its own setup. |
| `clost audit` | What needs attention: forks, subagent copies, links, orphans, stale state. `--fix` fixes what is safe to. |
| `clost check` | `trust.yaml` and the staff files against this machine. |
| `clost log [SESSION]` | What claudestra has done here: who did what to which session, and when. |

Every reading command takes `--json`.

**Running and organising sessions**: `clost session …`

| Command | |
| :--- | :--- |
| `start`, `stop`, `restart` | Run sessions in claudestra's tmux session. |
| `type SESSION TEXT` | Type a line into a running session and press Enter. |
| `peek SESSION` | The end of a running session's screen, without attaching. |
| `wait SESSIONS` | Wait until sessions are idle or stopped. |
| `attach [SESSION]` | Open claudestra's tmux at one session's window, or the whole of it (you only). Ctrl-b d detaches. |
| `compact SESSION` | Compact a stopped session. |
| `spawn FOLDER` | Begin a new session in a folder, with `--prompt`, `--name`, and `--staff` to hire it. A session's spawn is always hired. |
| `rename SESSION NAME` | Rename a session as `/rename` does. |
| `move SESSION FOLDER` | Refile a stopped session under another folder, as if it had always run there. |

`move`, `machine send` and `machine fetch` take `--copy-memory` to copy the project's auto-memory too, adding only what the destination lacks.

`clost autostart` starts this machine's autostart staffers; the login unit runs it at login.

**The staff**: `clost staff list | hire | dismiss | describe`; `staff list --tree` shows who manages whom.

**The trash**: `clost trash list | add | restore | purge`. Claude Code has no per-session delete; claudestra moves a session and every store keyed by it to a trash, puts it back exactly with `restore`, and only `purge` deletes.

**Other machines**: `clost machine list | send | fetch` move a stopped session between machines (you only).

**Installing parts one at a time**: `clost install guard | remote-control | login-unit | completion`

**Trust**: `clost trust show | grant | revoke | autostart | protect | machine` (changes are yours alone)

**Preferences**: `clost preferences` shows them; `clost preferences KEY [VALUE]` sets one (you only). Sessions follow them:

| Preference | |
| :--- | :--- |
| `finished-transcripts` | Once a session's work has gone out: `keep` its conversation, treat it as `disposable`, or `ask`. |
| `fan-out-model` | When a session runs many subagents: the `same` model, a `cheaper` one for a heavy fan-out, or `ask`. |
| `update-reminders` | `yes` (the default) or `no`: a reminder at your terminal when a newer release is out. |

`clost help` is `-h`, and `clost version` is `-v`.

**Removing it**: `clost uninstall` takes out the guard, shell completion and the login unit; then disable the plugin and run `uv tool uninstall claudestra`. Your config folder is kept.

## Shell completion

`clost install completion` installs completion for `claudestra` and `clost` in zsh, bash or fish; the plugin does this for you. `clost install completion --print` prints the script for a shell set up by hand.

## Configuration

Everything claudestra keeps is in `$XDG_CONFIG_HOME/claudestra/` (`~/.config/claudestra/`): `trust.yaml`, the staff files in `staff.d/`, `preferences.yaml`, and the guard. Where a path differs between machines, it is given for each machine, so the folder can be kept in step between them, for example with Syncthing. Change it only through claudestra's commands; the guard refuses a session's tool call into it.

## Developing

```
uv sync
uv run pytest
uv run ruff check
uv run ruff format
claude plugin test plugin
```

Install a checkout with `uv tool install --editable .`; an editable install is never reminded of updates. Tests never touch real sessions: they use fixture homes, a fake `/proc`, their own tmux server and a stand-in for `claude`.
