# claudestra: design

How claudestra is built and why, and the facts about Claude Code's files it relies on. `claudestra --help` lists the commands; this file says what they rest on. Each rule is stated once, here, and the code points back to the section that states it.

## 1. What it is

claudestra runs long-lived Claude Code sessions as a machine's **staff**, with a chain of command. It keeps track of every session on each of the user's machines, starts and stops sessions in a tmux session of its own with Remote Control on, lets sessions manage other sessions within limits the user sets, moves sessions between folders and between machines, finds forks, orphans and stale state, and removes sessions to a trash rather than deleting them.

It is a Python package with one command, `claudestra`, also installed as `clost`. A Claude Code plugin, in `plugin/`, installs it: when a session starts, it installs the version it pins with `uv tool install` if that is not the one installed, then runs `claudestra install guard` (§6.5) and `claudestra install completion` (§10), so both are put back at every start, and reminds the user to run `claudestra setup` until they have (§6.6); it ships four skills, named under the plugin's namespace: `claudestra:cli`, the commands and who may run them; `claudestra:sessions`, sessions on disk (finished, removed, forked, filed, moved); `claudestra:coordination`, messaging, briefing and handing work to other sessions; and `claudestra:fan-outs`, running many subagents on one job. They are separate so that each loads when its task comes up, whether or not the session thinks of claudestra. It reads Claude Code's files directly, since Claude Code has no interface for most of what it needs, and it keeps no database: everything is read from disk each time.

The words used throughout:

| Word | Means |
| :--- | :--- |
| **user** | The person whose machines and Claude Code sessions these are, at a terminal. |
| **session** | Any Claude Code session ID, with its transcript and the other files Claude Code keeps for it. |
| **staffer** | A session on the staff: one with a staff file in `staff.d/` giving its name, the folder it works in on each machine, and what it works on (§6.2). |
| **scope** | Authority the user grants a staffer in `trust.yaml`: `device` or `folder` (§6.1). |
| **manager** | A staffer with `folder` scope. It manages the specialists whose folders lie inside its own. |
| **device scope** | A staffer with `device` scope: the machine's top manager under the user. |
| **specialist** | A staffer with no scope. |
| **subject** | Whoever is calling claudestra: the user, a session, or claudestra's login unit (§6.4). |

Claude Code uses "agent" for its own subagents, so claudestra does not use the word for any of these.

## 2. Principles

- **It guards against mistakes; it is not a security boundary.** Every session runs as the user's own Unix account and could edit any file or run `claude` directly. claudestra makes the safe path the easy one, refuses what would break a session, and logs what it did. Keeping sessions from going round it is the job of Claude Code's permission rules and sandbox (§6.5); a session the user lets run with permissions bypassed, or whose escape the user approves, is outside what claudestra can stop.
- **It is never a way round a permission decision.** A session runs a changing command only where the user allows it in Claude Code's settings. claudestra's own checks narrow that permission and never replace it, and nothing it reads from another session, a staff file or a transcript counts as the user's approval.
- **The subject comes from the process chain, never from an argument** (§6.4). A session acting on another's request is the subject itself, not the one who asked.
- **Read fresh.** Claude Code changes its files underneath any copy, so claudestra reads the disk on every command, and reads it again inside its lock before it changes anything (§5).
- **One home per session.** A session's transcript lives under one folder on one machine. Two copies are a fork, and no operation leaves a copy behind.
- **Nothing is deleted except by `purge`.** A trashed session goes to claudestra's trash with a manifest, and `restore` puts it back exactly.
- **Every fact about Claude Code's files that claudestra relies on is checked on the machine it runs on** (`claudestra doctor`, §3), and a changing command refuses to run if a check it depends on fails.

## 3. Facts it rests on

Claude Code's documentation calls its on-disk format internal and liable to change on any release. claudestra therefore reads it defensively, checks `version` fields, and verifies each fact below with a named `claudestra doctor` check, which reports pass, fail or not observable; an action refuses while a check it depends on fails. A check on a fact no action relies on only warns, and blocks nothing: `versions` and `record-types`, since Claude Code updates every few days, the facts an action depends on are checked on their own, and a move rewrites `cwd` in a record of any type; `env-session-id`, since the caller is identified from the process chain (§6.4); `bridge-ids`, whose mismatch makes a lookup by Remote Control ID miss rather than find another session; `subagents`, which only `audit` reads; and `claude-agents`. The facts were established against Claude Code 2.1.296 and its documentation, and checked again against 2.1.301 (code.claude.com/docs: sessions, claude-directory, agent-view, env-vars, cli-reference).

**Identity**

- A **session ID** is a UUID, and names the session's transcript.
- A **running session** has `~/.claude/sessions/<pid>.json` (`pid`, `sessionId`, `cwd`, `procStart`, `kind`, `status`, `name`, `nameSource`, `bridgeSessionId`, `messagingSocketPath`, `pidDomain`, `version`), beside a secret `<pid>.<hex>.key` which claudestra never reads. `procStart` is field 22 of `/proc/<pid>/stat`, so a session is running when the file exists **and** its `procStart` matches the live process, never on the file alone. A clean exit removes the file and the messaging socket; a crash leaves either behind.
- Child processes get `CLAUDE_CODE_SESSION_ID`, `CLAUDE_PID` and the messaging socket. After `--continue` or a bare `--resume` the session ID there may be the one the process started with, which is one reason the caller is identified from the process chain instead (§6.4).
- **Remote Control IDs** appear as `session_<x>` (pid file, environment) and `cse_<x>` (transcripts, job state), sharing the suffix. A background job is known by the first eight characters of its session's ID.

**Where sessions are filed**

- A transcript is `~/.claude/projects/<slug>/<sessionId>.jsonl`. The slug is the folder the session started in, with every character other than an ASCII letter or digit turned into `-`. **The slug is lossy**: `a b`, `a.b`, `a-b` and `a/b` all give the same slug, so a slug cannot be turned back into a folder. Past 200 characters Claude Code truncates it and appends a hash claudestra cannot reproduce, so such a folder is refused as a destination.
- **A multi-root workspace's other folders redirect.** Each one's slug folder holds `.session-aliases`, one line naming the slug folder its sessions are filed under instead, the workspace's first folder's. Wherever claudestra works out where a folder's sessions are filed, it follows that redirect.
- `--resume <id>` searches every project and resolves only when exactly one holds the ID, so a duplicated transcript cannot be resumed. **Resuming from any folder other than the one a session is filed under forks it**, so a staffer's folder must be exactly that folder, redirects followed (§6.2).
- Beside a transcript, `<id>/` holds `subagents/agent-<id>.jsonl` with `.meta.json`, `tool-results/` and `custom-title.json`. A session that changed directory is split, with later tool results under the new folder's slug. Set-aside copies (`<id>.orphaned-…`, `<id>.jsonl.superseded-…`) sit beside a transcript.
- Other stores are keyed by session ID: `file-history/`, `session-env/`, and, documented though rarely seen, `uploads/`, `dev-mods/` and `image-cache/`. `jobs/<short>/state.json` holds a background job's own `cwd` and transcript path. `history.jsonl` lines name sessions, and `~/.claude.json` keeps a `lastSessionId` per project; claudestra writes neither.
- **Stores can hold symlinks.** A session continued into another may have its subagent transcripts linked to the files under the old one. So readers treat an unreadable file as unreadable rather than failing, comparisons use `lstat`, and `trash`, `move`, `send` and `fetch` refuse a session whose stores hold a link or are the target of one, until the user settles which session owns the file (§9).
- Each slug folder may hold `memory/`, the project's auto-memory, kept per project rather than per session. claudestra never moves or trashes it; `--copy-memory` copies it with a session (§8).

**Transcripts**

- Records link by `uuid` and `parentUuid`. There is no fork field, so a fork shows only as `uuid`s shared between two transcripts. Compaction stays in the same file: a `system` record with `subtype: compact_boundary`, then a `user` record with `isCompactSummary: true`.
- Metadata records are appended again and again, and the last one wins: `custom-title` and `agent-name` (both written by `/rename`, with `<id>/custom-title.json`), `ai-title`, `bridge-session`, `last-prompt`, `cost-state`, `mode`, `permission-mode`, `continued-in` and others. None holds a path. The known record types are listed in `claude_fs.KNOWN_RECORD_TYPES`, and `doctor` reports any other.
- From 2.1.300, `api-request`, `api-request-blob` and `api-request-shape` records log the requests sent to the API. They carry the session's ID and neither a `uuid` nor a `cwd`, so forks, moves and the counts in `summary` pass them by.
- User records carry `origin.kind` (`human`, `peer`, `task-notification`), so the user's prompts can be told apart from messages relayed by other sessions.
- Subagent transcripts' message records carry `isSidechain: true` and a session ID, normally the parent's. Which session a subagent belongs to is therefore a question for `claudestra audit subagents`.
- Lines can hold invalid UTF-8, from cut tool output, so a rewrite works on bytes and changes only the `cwd` values.

**Claude Code's own commands**

- `claude agents --json --all` is the supported view of background sessions; `jobs/*/state.json` and the daemon's files are not a stable interface.
- `claude project purge [path]` deletes a whole project, its `memory/` included, and there is no per-session delete; `cleanupPeriodDays` deletes by age. That is why claudestra has its own `trash` (§9).

## 4. The model

Everything is computed from disk on each command, into these objects:

- **Machine**: a hostname, and claudestra's derived machine ID: HMAC-SHA256 keyed by `/etc/machine-id` over claudestra's app ID, cut to a version-4 UUID, as `systemd-id128 machine-id --app-specific` computes it. The raw `/etc/machine-id` is never written anywhere that leaves the machine. `trust.yaml` pins each machine's derived ID beside its hostname, and claudestra changes nothing where the two disagree, so a renamed or cloned machine cannot pass as another.
- **Session**: keyed by its ID. It holds only the ID and reads everything else when asked: its names (latest first, labels only, never trusted for authority), the slugs holding its transcript, its folder, its runs and jobs, and its stores. Its **folder** is the one it started in where that files under its slug, and otherwise the one known folder that files there. Any of these finds it: the full ID, an 8+ character prefix, a Remote Control ID, a job's short ID, or its title.
- **Run**: a live process hosting a session, keyed by pid and `procStart`. At most one run per session; two is a fork in progress.
- **Staffer**: a session with a staff file. In the code it is `Staffer`, a subclass of `Session`, which adds what needs the staff file: its name on the staff, its folder on each machine, its scope, its managers, and whether it starts at login. Whether a session is on the staff can change at any time, so a staffer reads its staff file each time it is asked, and refuses once the file is gone.

Code that does not care whether a session is on the staff asks the context for a session (`Context.session`), and where it matters asks `on_staff` and fetches the staffer explicitly. Code that needs a staffer asks for one (`Context.staffer`), which refuses a session off the staff.

**What claudestra writes**, each through a named, logged action: a session's stores (moved or trashed), the trash and its manifests, a moved session's `cwd` fields and its job's `state.json`, the title records of a stopped session it renames, keystrokes typed into a session's window, `trust.yaml` (§6.1) and the staff files (§6.2). Never `~/.claude.json` or Claude Code's settings. Its own state is under `$XDG_STATE_HOME/claudestra/`: the log, the lock, and backups of what it rewrites. Staging for transfers is under `$XDG_CACHE_HOME/claudestra/`.

## 5. Actions

Every command is an **action**: a subject, a verb and an object. The subject is whoever is calling (§6.4), the verb is the action's class, and the object is a session, a staffer, a trash entry, a machine, or nothing. Each action is its own file under `actions/`, and answers four questions in order:

| Method | Asks |
| :--- | :--- |
| `check()` | Is it well formed, and possible now? A name is one line, a folder exists, the session is stopped, nothing unsent sits in its prompt. |
| `authorize()` | May this subject take it? Each action declares its rule as `who` (§6.1). |
| `describe()` | What will happen, line by line, for the confirmation and `--dry-run`. |
| `run()` | Do it. |

**Performing an action** follows one fixed order, in `Action.perform`:

1. The preamble: this machine matches `trust.yaml`, the config has no errors, `--home`, `--config` and `$CLAUDESTRA_CONFIG` are honoured only for the user, and the `doctor` checks the action depends on pass.
2. `check`, `authorize` and `describe`, then show the plan. `--dry-run` stops here; at a terminal the user is asked (`-y` skips the question), and a session is never asked.
3. Inside the lock, read the disk again, `check` and `authorize` again, and refuse if the plan changed while the user was deciding.
4. `run`, then read the disk again for whatever reads next.

The lock is not waited on: a second claudestra that wants to change something is refused. An action varies this order only through two flags, never by replacing it: one that changes nothing (`changes = False`, the reading actions) is only checked, authorized and run; one that must not hold the lock (`locks = False`) skips the lock, which only `attach` does, since its process becomes tmux.

**Undoing.** An action that can be undone says so (`reversible`) and has an `undo()`; claudestra refuses at import an action that claims one without the other, or that declares no rule. An operation that fails part way puts back what it did (`ops/common.Journal`, and for a transfer, on both machines) and says so.

**Grouping actions**:

- A **transaction** runs actions all or nothing. Each is checked and authorized before any runs; they run in order under one lock; if one fails, those already run are undone, newest first. Every undo is tried even if one fails, and the original failure is what is reported. Only the last action may be one that cannot be undone, so nothing after it can fail. `audit --fix` runs its fixes as a transaction.
- A **workflow** runs steps in order with waits between them, and is not all or nothing: it stops at the first failure, runs its closing steps (such as stopping what it started), and says how far it got. Every step is authorized before the first runs, so a workflow is never refused half way. `compact` is one: start the stopped session in claudestra's tmux, wait until it is idle, type `/compact`, wait for the compaction to be recorded, and stop it again. A running session is refused, since `/compact` is typed in it directly.

**Spawning a session.** `session spawn FOLDER` begins a new session in claudestra's tmux, in `FOLDER`, with Remote Control on. claudestra chooses its ID and passes it with `--session-id`, so the session can be named and reached from its first moment; `--prompt` is its first prompt, and `--name` its name, shown and used to reach it. It starts in the user's default permission mode, never the spawner's, so a session running with permissions bypassed does not hand that on. With `--staff`, which needs `--name`, `--description` and `--prompt`, it is also hired into `FOLDER` as a specialist before it starts, and the hire is taken back if it fails to start or exits at once; a scope stays the user's to grant (`trust`). **A session's spawn is always hired**, with its brief, so that its spawner can run it and it writes a transcript at once: only the user spawns a session off the staff, which would otherwise be the user's alone to run.

**Several sessions at once.** `session start`, `stop` and `restart` show every session's plan before the one question. `trash add` with several sessions is a transaction: one plan, one question, and a refusal for any of them trashes none.

**Typing and renaming a running session.** `type` types one line into a session running in claudestra's tmux and presses Enter. It refuses a session that is mid-turn, or whose prompt holds unsent text, so nothing anyone was writing is sent or overwritten. A running Claude Code appends its own title records and the last one wins, so `rename` of a running session types `/rename` into its window and waits for `custom-title.json` to carry the new name, instead of writing the files; a session running outside claudestra's tmux is refused. A staffer's staff file follows its rename.

**The audit** reports what needs attention, one class per kind of problem (`audit_errors.py`): forks, subagent copies, links, broken redirects, a session filed under two slugs, two runs of one session, orphaned stores, stale pid files and keys, orphaned jobs, slugs several known folders share, stale project entries, and staffers whose staff file name differs from their session's title. A problem that claudestra can fix safely returns the fixing action from `fix()`; `audit --fix` takes those, authorizes each as its own action, runs the ones the caller may take as a transaction, and reports the rest with the reason. Today the only such fix is bringing a staff file's name into step with its session's title, as after `/rename` typed inside the session. A folder that differs is reported and never followed, since following it could widen a manager's reach.

**Restricted mode.** When any Claude process is in the chain that called claudestra, a session may be driving the terminal, so whatever is the user's alone is refused, whoever the subject is taken to be. claudestra says so first, on stderr, with the Claude processes it found.

## 6. Trust

### 6.1 `trust.yaml` and who may do what

`trust.yaml` is the user's, one file for all their machines, since sessions move between them. It is written by `claudestra trust`, which is the user's alone, in claudestra's own layout: machines first, then sessions, each session ID followed by a comment with its current name, regenerated on every write. What is written must read back as intended, and every change can be undone.

```yaml
machines:
  <hostname>:
    home: <its home folder>
    machine_id: <claudestra's derived ID, §4>
    ssh: <user@address>   # only on a machine that accepts connections (§8)
    autostart:            # staffers started at login on this machine (§7)
      - <session ID>
    protected:            # folders whose sessions may not leave them (§6.3)
      - <folder>
sessions:
  <session ID>: # <its name, generated>
    scope: device          # or: folder
```

**Scope belongs to staffers.** `trust grant` refuses a session off the staff, and a scope whose session is neither on the staff nor dismissed is a config error. A dismissed staffer's scope stays in the file but is held by nobody until the staffer is rehired.

**The chain of command.** The scopes exist so that no real work happens without its manager supervising it:

- **The user**, at a terminal with no Claude process in the chain, may do anything, and is alone in what touches the machine or the config: `trust`, `purge`, `send`, `fetch`, `attach`, installing the login unit, and turning Remote Control on (§7.1). Installing the guard (§6.5) is open to anyone, since it only adds protection.
- **A manager** (`folder` scope) runs its own specialists, the unscoped staffers whose folders lie inside its own: it starts, stops, compacts, renames and types into them, hires and dismisses specialists in its folder, spawns new sessions there, and describes what they work on. Its folder is the one its staff file gives, counted only when its session is filed there and its process runs there, so editing a staff file cannot widen its reach.
- **A device scope** organises the machine: it starts, stops, compacts and moves managers, and runs, hires, dismisses and describes any specialist whose folder no manager holds, since nobody else would. It may rename any staffer without device scope and type into any staffer but itself. It may spawn a new session in any folder on its machine that no manager holds, protected ones included; where a manager holds the folder, it asks that manager by message to spawn the specialist. It may trash a session that is not on the staff, and restore from the trash.
- **The login unit** may only start this machine's autostart staffers (§7).
- **No session acts on itself**, except to keep its own staff file current: its name in step with its title (`fix-name`) and what it works on (`describe`). **Only the user, a device scope and a manager begin new sessions**, through `spawn` (§5).

Each action declares its own rule as `who`, one of four kinds (`actions/permissions.py`): `Relations`, the subject's relations to the session it acts on; `ToFolder`, for hiring, the relation the subject would have to the specialist hired, worked out from the folder it will work in; `Kinds`, the kinds of subject allowed, for an action whose object is not a session; and `Anyone`, for reading actions and for `audit --fix`, whose fixes are each authorized as their own action. `claudestra permissions` prints every changing action's rule, and a test checks the tables below against the code.

The relations, with D for a device scope:

| Column | The subject is | and the session is |
| :--- | :--- | :--- |
| User | the user, with no Claude process in the chain | any |
| Manager | a manager | a specialist it manages |
| D: manager | a device scope | a manager |
| D: unmanaged | a device scope | a specialist no manager holds |
| D: managed | a device scope | a specialist under a manager |
| D: device | a device scope | another device scope |
| D: off staff | a device scope | a session not on the staff |
| Login | the login unit | an autostart staffer on this machine |

**Actions on a session:**

| Action | User | Manager | D: manager | D: unmanaged | D: managed | D: device | D: off staff | Login |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| start | ✅ | ✅ | ✅ | ✅ | | | | ✅ |
| stop | ✅ | ✅ | ✅ | ✅ | | | | |
| compact | ✅ | ✅ | ✅ | ✅ | | | | |
| type | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | | |
| rename | ✅ | ✅ | ✅ | ✅ | ✅ | | | |
| fix-name | ✅ | ✅ | ✅ | ✅ | ✅ | | | |
| describe | ✅ | ✅ | | ✅ | | | | |
| hire | ✅ | ✅ | | ✅ | | | | |
| spawn | ✅ | ✅ | | ✅ | | | | |
| dismiss | ✅ | ✅ | | ✅ | | | | |
| move | ✅ | | ✅ | | | | | |
| trash | ✅ | | | | | | ✅ | |
| send | ✅ | | | | | | | |

✅ allowed; ⚠️ allowed, with a caveat noted here; blank, refused. `fix-name` and `describe` also allow the staffer itself. For `hire` and `spawn`, the columns are the relation the subject would have to the session once hired or begun.

**Actions on anything else:**

| Action | Who |
| :--- | :--- |
| restore | the user, or a device scope |
| attach, fetch, install, preferences, purge, remote-control, uninstall | the user |
| trust grant, trust revoke, trust autostart, trust protect, trust machine | the user |

Anything the user alone may do is refused in restricted mode (§5). A session off the staff can be started, stopped and renamed only by the user, since no relation but the user's reaches it.

### 6.2 Staff files

A staffer's staff file is `staff.d/<session ID>.yaml` in the config folder (`$XDG_CONFIG_HOME/claudestra/`), named by the full session ID, which appears nowhere else in it:

```yaml
name: <its name on the staff>
folder:
  <hostname>: <the folder it works in there, ~ for the home folder>
description: <what it works on>
```

- **`staff.d/` is claudestra's to write.** `hire` writes a staff file, with a header saying so, and `rename`, `move`, `send`, `fix-name` and `describe` change it. `describe` changes what a staffer works on; whoever may hire a staffer may describe it, and so may the staffer itself. No session edits it directly, and `claudestra check` warns of a staff file claudestra did not write.
- **Hiring**: the name defaults to the session's title and the folder to where the session is filed; the description is required. Who may hire is worked out from that folder (§6.1). A session never hires itself.
- **Dismissing** moves the staff file to `staff-dismissed.d/` exactly as it is. The session is untouched, and so is any scope it holds. `hire` on a dismissed session brings the file back, with whatever is given written over it, and its scope with it. Dismissal is refused while the staffer runs in claudestra's tmux or starts at login on any machine, since either would leave something nobody answers for; and `trash` refuses a staffer, so a staffer is dismissed before its session is trashed.
- **Its folder must be exactly the folder its session is filed under, redirects followed**, since resuming from any other folder forks the session (§3); and where the transcript records the folder the session started in, that very folder, since folders can share a slug. Folders are compared by exact slug. `claudestra check` reports a mismatch as an error, and `start` refuses it.
- **Whether it starts at login is not the staffer's to say**: `autostart` in `trust.yaml` decides, and an `autostart` key in a staff file is an error.
- Trust never comes from a staff file except through the folder check in §6.1.

### 6.3 Protection

Each machine's `protected` folders are folders whose sessions must not leave them. A protected session is never moved, sent or fetched out of its protected folder; everything else works as anywhere, so a manager inside one can run the sessions there. A session is protected if its folder is inside a protected folder, **or** if its slug equals a protected folder's slug or begins with it followed by `-`. Both tests apply, so a folder that merely shares a slug cannot slip past, and the slug test errs towards protecting more. `send` also needs the user to type the session's full ID, whatever the list says, because what a transcript read is not visible from its folder.

### 6.4 Identifying the caller

`proctree.py` walks the caller's process chain and picks out every Claude process in it, by executable or command name `claude`, or by a live session file naming the process, and maps each to its session through its pid file. The nearest Claude process is the subject: its session, with the scope `trust.yaml` gives it while it is on the staff. A Claude process with no matching session file is refused, as is a process with Claude Code's variables but no Claude process above it, and one with no terminal. With no Claude process in the chain, the subject is the user, at a terminal. The login unit is recognised by its systemd invocation ID **and** its own cgroup, which a `systemd-run` started by a session cannot fake. Test stand-ins are honoured only for the user, or on a separate tmux socket.

### 6.5 Keeping sessions out of the config

claudestra's checks bind only sessions that go through claudestra, so the config folder needs Claude Code's own protection as well. Claude Code protects `~/.claude/`, but not `$XDG_CONFIG_HOME/claudestra/`. What protects it, tested against Claude Code 2.1.296:

- **Deny rules** in Claude Code's settings, `Read(//home/*/.config/claudestra/**)` and `Edit(//home/*/.config/claudestra/**)`, plus the resolved path where `$XDG_CONFIG_HOME` is set elsewhere, since a rule does not expand variables. They hold in every permission mode, bypass included, and catch the built-in tools and the shell's common file commands (`cat`, redirects, `sed`, `mv`, `cp`). They do not catch an interpreter opening the file itself.
- **The sandbox**, with the folder under `sandbox.filesystem.denyWrite` and `denyRead`, and `allowUnsandboxedCommands: false`. It catches the interpreter, and leaves the user's systemd bus unreachable, so a session cannot start a process outside it.
- **A `PreToolUse` hook**, `guard.py` in the config folder, run by claudestra's own Python; only the hook's entry in the settings names this machine's paths. It refuses a tool call whose path lies in the folder (resolved through links) or whose shell command holds a word that resolves into it: each word, and each run inside a word that starts at the root, `~` or a variable, is expanded and resolved, a relative one against the session's folder. So `cat ~/.config/claudestra/trust.yaml` and an interpreter opening `$XDG_CONFIG_HOME/claudestra/…` are refused, which the deny rules miss, while a command that only mentions the folder's name, such as a search of these docs for it, runs. A session working inside the folder is refused everything; it also refuses an edit of the settings that would remove it. Hooks hold in every permission mode, bypass included, tested against Claude Code 2.1.296. It matches text, so a session set on hiding the path gets past it; it is there for mistakes, as the rest of claudestra is (§2). It fails open on input it cannot read, rather than block every call.
- Rules and hooks in the user's own settings can be removed by a session running with permissions bypassed (the hook refuses an edit that would remove it, but not an interpreter writing the file). Rules in managed settings (`/etc/claude-code/managed-settings.d/`) cannot, but installing them needs root.

**`claudestra install guard`** writes `guard.py` and adds the deny rules and the hook to the user's own settings, `~/.claude/settings.json`, keeping everything else there. Where the user has turned the sandbox on, it also hides the config folder from the sandbox and lists `claudestra *` and `clost *` under `sandbox.excludedCommands` (a bare name does not match a command with arguments), so that claudestra, which reads the config, runs outside it; turning the sandbox on, and `allowUnsandboxedCommands`, stay the user's. It only ever adds protection, so anyone may run it, a session included, and it asks nothing of the caller: claudestra's plugin runs it when every session starts, and nothing in claudestra takes the guard away. With `--managed` it changes nothing and prints a drop-in for `/etc/claude-code/managed-settings.d/claudestra.json`, holding the rules and the hook, with the command that installs it as root. `claudestra doctor guard` fails while a rule or the hook is in neither the user's settings nor managed settings, or `guard.py` is not as claudestra writes it. `guard.py` is the same on every machine: it finds the config folder from where it lies and the home folder as it runs, so a config folder kept in step between machines carries it unchanged.

### 6.6 Setting up, and the user's preferences

**`claudestra setup`** walks the user through putting claudestra on a machine, at their terminal; it refuses anywhere else, since every step but the guard and completion is theirs alone. It takes each step only where it is not done yet, showing the plan and asking first, and each step is an action authorized as itself, so it can do nothing the user could not do with the commands one by one: this machine under `machines` in `trust.yaml`; the guard (§6.5) and Remote Control (§7.1); a device-scope manager, chosen from this machine's staffers or spawned in the home folder, given device scope and started at login; the login unit (§7); shell completion (§10); and the preferences below. Run again, it skips what is done. Until the preferences are chosen, the plugin reminds the user, when a session starts, to run it.

**Preferences** are the user's choices about how sessions work for them, where users differ and no default is right for everyone. They live in `preferences.yaml` in the config folder, so they are the same on every machine; sessions read them with `claudestra preferences`, since the folder is closed to them, and a preference not yet chosen means asking the user. Bare, `claudestra preferences` shows them; given a preference, it sets it, which is the user's alone.

| Preference | Choices | Unchosen |
| :--- | :--- | :--- |
| `finished-transcripts` | `keep`; `disposable` once the session's work has gone out; `ask` | ask |
| `fan-out-model` | `same` model as the session; a `cheaper` one for a heavy fan-out, after saying the projection; `ask` | ask |
| `update-reminders` | `yes`, `no` | yes |

**Update reminders.** At the user's terminal, at most once a day, claudestra asks the git remote it was installed from, as uv recorded it, for its newest release tag, and says so on stderr when it is newer than the one running. It never prompts for a password, says nothing when the remote cannot be asked, and is never shown to a session. An editable install, or one from a local folder, is a developer's, updated by pulling, and is never checked.

## 7. Runners

- **tmux** (`runners/tmux.py`): one tmux session, `claudestra`, with one window per session it runs, showing the session's name and found by its session ID, held in the window option `@claudestra_session`, so a rename never loses it (a rename of a running session renames its window too). A runner is given only what it needs to run a session (`Launch`: its ID, its name and its folder): a staffer runs by its name on the staff, from the folder its staff file gives; any other session by its title, from the folder it is filed under. Remote Control is turned on with the same name. `remain-on-exit` is set before the session starts, so one that exits at once leaves its window for `attach`. No Claude Code variable reaches the window, from the caller or from a tmux server someone else started, and its `PATH` holds the folders of `claude` and `claudestra` first, so a session the login unit starts can call both. `start` waits for the run's session file and reports its pid; `stop` sends two Ctrl-Cs, then SIGTERM, and is refused mid-turn without `--force`.
- **Looking at a running session.** `session peek` prints the end of a session's screen without attaching, so a manager can see a staffer held at a question or a permission prompt; anyone may, as anyone may read a transcript. `session wait` holds until sessions are idle or stopped, for briefing a staffer and waiting for its turn to end. `session attach SESSION`, the user's, opens claudestra's tmux at that session's window through a viewing session of its own, grouped with claudestra's, so going to the window moves no one else who is attached; the viewing session goes when the user detaches. Without a session, it attaches to the whole tmux session.
- **A run the user started**, outside claudestra's tmux, is seen and never stopped.
- **The login unit**, `claudestra-autostart.service`, is a one-shot systemd user unit that runs `claudestra autostart` at login, starting the machine's autostart staffers. It records the exact paths of `claudestra` and `claude` found when it is installed, since the systemd user manager's `PATH` need not hold them; when either moves, the unit is reinstalled, and `claudestra doctor login-unit` reports a unit that differs from what claudestra would write.

### 7.1 Remote Control is required

claudestra requires Remote Control on for **every** session on a machine, at the user's level, not only for the sessions it starts. Staffers coordinate by messaging each other, a manager briefs and follows its staffers that way, and sessions on another machine are reached only through Remote Control; a session without it cannot be addressed, and cannot be answered. `start` turns it on with `--remote-control` for the sessions it runs, and requires the setting as well.

Claude Code reads `remoteControlAtStartup`, tested against 2.1.300: `false` in a folder's own `.claude/settings.json` or `settings.local.json` turns it off there, whatever else says, and a folder's settings cannot turn it on; otherwise managed settings decide where they set it, then the user's `~/.claude/settings.json`, then an older copy in `~/.claude.json`. `claudestra doctor remote-control` fails while it is not on at that level, or while a staffer's folder on this machine turns it off, and `start` refuses until it passes. At the user's terminal, `doctor` offers to turn it on. **`claudestra install remote-control`** sets it in the user's settings, keeping everything else there; it is the user's alone, since it makes every session on the machine reachable through the user's account. It refuses where managed settings turn it off, and leaves a folder's own settings to the user.

## 8. Moving between machines

- **Who connects**: only a machine with an `ssh` address in `trust.yaml` accepts connections, so a transfer runs on the other one. The far side is checked by hostname and derived machine ID first. It runs `portable.py` and `remote_helper.py`, shipped as one script, and needs no claudestra installed.
- **What moves**: a session's stores, with its subagents and file history, but not the project's `memory/`. The destination folder comes from the staffer's staff file for that machine, or `--to`; home folders differ between machines, so they are mapped too, and the destination slug is worked out on the destination.
- **How**: refuse if the session runs on either side, is protected, or the destination already has it; stage, rewrite the `cwd` fields, copy, verify checksums on both sides, and only then move the source's stores to its trash. A failure part way takes back whatever arrived, so the session keeps one home.
- A background job's `state.json` is not carried; it belongs to the machine's supervisor.
- **The project's memory** stays where it is, since it belongs to the project and the sessions left there may still read it. With `--copy-memory` (on `machine send`, `machine fetch` and `session move`) it is copied to the destination's project after the session has arrived: only files missing there are added, and a file there that differs refuses the whole move before anything changes, so nothing is overwritten or merged by guesswork. A memory copy that fails after the session has moved says so, and leaves the session where it arrived.

## 9. Moving, removing and settling sessions

**A moved session is rewritten as if it had always been there.** Claude Code labels a session by the folder it started in, so a session moved to another folder, or whose project folder was renamed, otherwise shows a folder that is wrong or gone. `move` takes every store with the session, merges a split session's folders, and changes only the `cwd` fields, since messages, tool calls and tool results mention paths as they were said and done. `--exact` rewrites only the launch folder itself, for a session that also did real work in that folder's subfolders. `send` and `fetch` do the same between machines.

**Removing a session.** Claude Code has no command to delete one session, so claudestra's `trash` moves every store of a session into its trash with a manifest, `restore` puts it back exactly, and only `purge` deletes. `trash` refuses a running session, which covers one that is open but idle: such a session, once its files are gone, writes a stub back when it exits, which then appears as a duplicate. A crash leaves no session file, so `trash` also refuses a session written in the last few minutes. It refuses a session filed in a protected folder, and a staffer, which is dismissed first.

**Forks.** A fork is a session whose transcript begins with a copy of another's: `--fork-session`, a resume that branched, or the same session resumed in two places at once. The copied records keep their `uuid`, so two transcripts that share any `uuid` are copies of one history. `audit forks` groups them, and for each copy counts the records no other copy has and, among those, the prompts the user typed. A copy with none of its own prompts is contained in the others and is redundant; one with prompts of its own holds history the others lack, and which to keep is the user's call. The check is per machine, since transcripts are not synced.

**Linked subagent transcripts.** A session continued into a new one may read some subagent transcripts through symlinks to the files under the old session, so two sessions share one file. Following the links makes them look like identical copies, and removing one copy leaves the links dangling, so claudestra compares with `lstat`, and `trash`, `move` and `send` refuse either session until the user decides which owns the file. `audit links` lists them.

## 10. The package

```
claudestra/
  DESIGN.md, AGENTS.md
  pyproject.toml, uv.lock
  src/claudestra/
    context.py          the one context per process: Claude Code's files, this machine, the config,
                        the subject, and the Claude processes in the chain
    session.py          Session and Staffer
    actions/            one file per action; base.py holds Action, SessionAction, ReadOnlyAction,
                        Transaction and Workflow; permissions.py the relations and the rules
    audit_errors.py     what the audit finds, one class per kind of problem
    portable.py         what both machines do, standard library only, shipped to the other machine
    remote_helper.py    the other machine's side of send and fetch
    claude_fs.py        read-only readers of Claude Code's files; the only module that knows the format
    model.py            the records read from disk; alias resolution
    trust.py            trust.yaml and the staff files, read
    proctree.py, caller.py   who is calling
    checks.py           claudestra doctor
    runners/            the tmux runner, and Launch
    ops/                the work on files, with no permission checks of their own
    cli/                the command line: parses arguments, finds the object (select.py), performs the action
  tests/                against fixture homes, a fake /proc, a stand-in for the other machine and for claude
```

**The command line.** Reading commands are at the top level (`ls`, `show`, `summary`, `whoami`, `permissions`, `doctor`, `audit`, `check`), with `preferences`, `setup`, `help` (as `-h`) and `version` (as `-v`); `log`, which reads back claudestra's record of what it did; `autostart`, which the login unit runs; and `uninstall`. Everything else is in a group: `session` (start, stop, restart, type, peek, wait, attach, compact, spawn, rename, move), `staff` (list, with `--tree` for who manages whom; hire, dismiss, describe), `trash` (list, add, restore, purge), `machine` (list, send, fetch), `install` (guard, remote-control, login-unit, completion) and `trust`. A bare group shows its help, as `-h` does; a bare command that gets and sets, such as `preferences`, gets. Every reading command takes `--json`, since sessions are its main readers.

**Uninstalling.** `claudestra uninstall`, the user's, takes out what claudestra put on the machine outside its package, so removing it leaves nothing broken behind: the guard (whose hook would otherwise name a Python that is gone), shell completion and the login unit. It keeps the config folder and the Remote Control setting, and says to disable the plugin, which would otherwise put the guard back, and to remove the CLI with `uv tool uninstall`. Bare `claudestra` at a terminal is a menu of every command, a group's by its full name.

**Selecting what a command acts on** goes through one module, `cli/select.py`. Given on the command line, a session, staffer, trash entry, machine, folder or choice is used as given. Left out at a terminal, it is picked from a list, which the command narrows by saying what it allows (`staff=False`, `running=False`, `scoped=True`, a staffer `on` a machine). Left out with no terminal, which is how a session runs claudestra, the command refuses and names what to give. So every command serves a person and a session alike.

**Completion.** `claudestra install completion` installs completion for `claudestra` and `clost` in the user's shell (zsh, bash or fish): the script in a file of its own, and for zsh and bash one marked line in the shell's startup file that sources it. It only adds completion, so anyone may run it, and the plugin does when a session starts. `--print` prints the script instead.

- **Dependencies**: Typer with rich output and questionary pickers for the command line, PyYAML, and libtmux, pinned to a minor version since its API still moves. Python is managed with uv.
- **Tests never touch real sessions.** The tests that drive tmux use a tmux server of their own and a stand-in for `claude`; real launches are checked by hand.
