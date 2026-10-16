# claudestra: notes for agents working on it

claudestra runs long-lived Claude Code sessions as a machine's staff, on one or more machines, with a chain of command: it keeps track of every session, starts and stops them in tmux, and decides who may manage whom. `DESIGN.md` says how it is built and why.

## Working here

- **Python with uv.** `uv sync` sets up the environment; nothing is installed with pip.
- **Before every commit:** `uv run pytest`, `uv run ruff check` and `uv run ruff format` (120 columns, set in `pyproject.toml`). The tests that drive tmux use their own tmux socket and a stand-in for `claude`; none reads the real `~/.claude`.
- **Notes stay local.** Design drafts, research and handoffs go in `.agents/notes/`, which git ignores, since the repository is meant to be public. Tracked files describe the code as it is; commit messages say what changed and why.

## Words

- **Session**: any Claude Code session ID.
- **Staffer**: a session with a staff file, `staff.d/<session ID>.yaml`, giving its name, its folder on each machine and its job. A **manager** is a staffer with folder scope, a **specialist** one with no scope; a device scope is the machine's top manager under the user.
- **Agent** is not used for any of these, since Claude Code uses it for its own subagents; in code, `agent` means only Claude Code's.

## How the code is laid out

- `context.py`: the one context per process (`Context.current()`): Claude Code's files, this machine, the trust config, the subject, and the Claude processes in the chain that called claudestra (`chain`, `restricted`).
- `session.py`: `Session(session_id)`, which holds only its ID and reads everything else through the context, and `Staffer(Session)`, a session on the staff, which adds what needs its staff file (scope, managers, `fix_name`). Their methods are factories for the actions on them. `Context.session(ref)` always gives a plain `Session`, for code that does not care; such code asks `on_staff` and guards explicitly. `Context.staffer(ref)` gives a `Staffer` or refuses, for code that needs one.
- `actions/`: one file per action. `base.py` holds `Action` (whose `perform` method fixes the order every action is checked, authorized, confirmed and run in), `SessionAction`, `ReadOnlyAction`, `Transaction` and `Workflow`. Every action declares who may take it as its `who`, one rule from `permissions.py` (`Relations`, `ToFolder`, `Kinds` or `Anyone`), which also works out the relations and refuses with the reason; `claudestra permissions` prints every changing action's rule. An action varies `perform` through its `changes`, `locks` and `machine_known` flags, never by overriding it.
- `audit_errors.py`: what `claudestra audit` finds, one class per kind of problem; one that claudestra can fix safely returns the fixing action from `fix()`, which `audit --fix` takes.
- `ops/` and `runners/`: the work on files and on tmux, with no permission checks of their own.
- `cli/`: parses arguments, finds the object, calls a factory, and performs the action or prints what a reading action returns. Every argument naming a session, staffer, trash entry, machine, folder or choice is taken through `cli/select.py`, which uses it as given, picks it at a terminal from a list the command narrows, or refuses off one; no command builds a picker of its own.

## Rules the design depends on

- **The subject comes from the process chain, never from an argument.** An action takes its subject from the context.
- **Each action declares who may take it**, in its own file; `actions/permissions.py` works out relations and refuses. `ops/` and `runners/` never check who is asking.
- **Restricted mode:** any Claude process in the chain refuses whatever is the user's alone, whoever the subject is taken to be.
- **Read fresh.** The model and the config are read from disk and read again inside the lock before an action runs, and after it.
- **The action tree is at most two levels deep:** `Action`, then `ReadOnlyAction` or `SessionAction` or a concrete action. What actions share goes in `ops/` and `runners/`, not in further base classes. Whether an action can be undone is its `reversible` property; one that is overrides `undo()`, and `Action.__init_subclass__` refuses one that does not, or that declares no `who`.
- **The config is claudestra's to write.** `trust.yaml` changes through `claudestra trust`, which is the user's alone; `staff.d/` through `hire`, `dismiss`, `rename`, `move` and `fix-name`. No session edits either directly.
