# Privacy

claudestra and its Claude Code plugin collect nothing and send nothing to the author or to anyone else. There is no telemetry and no account. Everything claudestra keeps, it keeps on your machine, in its config folder and in Claude Code's own files.

It reaches the network in three cases, each of which you control:

- **Installing the CLI.** With the plugin's `auto_install` option on, the plugin runs `uv tool install` when a session starts if the installed claudestra is not the version it pins. uv then fetches that release from GitHub, or from the `source` you set. The option is off unless you turn it on; with it off, the plugin only tells you the command to run.
- **Update reminders.** At your terminal, at most once a day, claudestra asks the git remote it was installed from for its newest release tag, to tell you when a newer one is out. It never does this for an editable install or one from a local folder, and never in a session. Turn it off with `claudestra preferences update-reminders no`.
- **Moving a session between your machines.** `claudestra machine send` and `machine fetch` connect over SSH to a machine you have listed in `trust.yaml`, and only when you run them.

Questions about this go to the [issues](https://github.com/adityaruplaha/claudestra/issues).
