# claudestra plugin

claudestra runs long-lived Claude Code sessions as a machine's staff, with a chain of command: it keeps track of every session, starts and stops sessions in tmux, lets sessions manage other sessions within limits the user sets, and removes sessions to a trash rather than deleting them. This plugin checks that the claudestra CLI is installed, keeps its guard in place, and ships the skills that teach sessions to use it. The CLI and its documentation are in the [repository](https://github.com/adityaruplaha/claudestra).

Linux only; it needs [uv](https://docs.astral.sh/uv/) and tmux.

Install it in Claude Code with:

```
/plugin install claudestra --marketplace adityaruplaha/claudestra
```

## What it does when a session starts

Each time a session starts, the plugin does the following in the background; the session does not wait for it.

1. **Checks for the claudestra CLI** at the version this plugin pins. The version is fixed in the plugin, so an update to the plugin is the only thing that changes it. If that version is not installed, the plugin installs nothing by default: it shows a notice with the command that installs it, `uv tool install --force git+https://github.com/adityaruplaha/claudestra@v<version>`, and does none of the steps below until it is installed. A session asked about claudestra offers to run the command, and asks before it does.

   With the **`auto_install`** option on (off by default; set it in `/config`), the plugin runs that command itself instead. The `source` option installs from somewhere else, such as a fork or a local checkout, which is installed editable; the notice then gives that command.

   Steps 2 to 4 run only once the pinned claudestra is installed.
2. **Puts claudestra's guard in place** by running `claudestra install guard`. The guard **changes the user's own Claude Code settings**, `~/.claude/settings.json`:
   - it adds `permissions.deny` rules that keep the `Read` and `Edit` tools, and the shell's common file commands, out of claudestra's config folder, `~/.config/claudestra/`;
   - it adds a `PreToolUse` hook, a script it writes into that folder, which refuses any tool call that names the folder and any edit of the settings that would take the hook out;
   - if the sandbox is on, it adds the folder to `sandbox.filesystem.denyRead` and `denyWrite`, and claudestra's commands to `sandbox.excludedCommands`.

   It only adds to the settings and keeps everything else in them. Because the guard lives in the user's settings, it stays in force while the plugin is disabled, and the plugin puts it back at every session's start if it has been removed.
3. **Installs shell completion** for `claudestra` and `clost` in zsh, bash or fish: a script under `~/.local/share/claudestra/` with one marked line in `~/.zshrc` or `~/.bashrc` that loads it, or a file in fish's completions folder.
4. **Reminds the user to run `claudestra setup`**, with a notice, until they have chosen their preferences.

claudestra reads Claude Code's own files on your machine, the session transcripts among them, to list, summarise, move and audit sessions; it reads them only there and only when one of its commands is run. The plugin sends nothing anywhere. Its only network access is uv fetching the pinned release from GitHub, with `auto_install` on.

## Undoing it

1. Run `claudestra uninstall` in a terminal. It takes out the guard, shell completion and the login unit, if `claudestra setup` installed one. It keeps claudestra's config folder.
2. Disable or uninstall the plugin, or the next session puts the guard back.
3. Run `uv tool uninstall claudestra`.

## Example prompts

- "Which sessions are running on this machine, and which of them are on the staff?"
- "Start the staffer that manages ~/Projects/website and brief it to fix the broken links on the home page, then tell me when it reports back."
- "Is session 3f2a91c0 finished? If its work has gone out, move it to the trash."
