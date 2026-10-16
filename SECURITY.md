# Security

Please report a vulnerability privately, through GitHub's private vulnerability reporting: the **Report a vulnerability** button on the repository's [Security](https://github.com/adityaruplaha/claudestra/security) tab. Do not open a public issue for it.

claudestra's guard keeps sessions out of its config folder by mistake; it is not a sandbox, and a session set on getting round it, or one run with permissions bypassed, is outside what it can stop (`DESIGN.md` §2 and §6.5). A way for a session to act as another, to widen its own scope, or to reach what the guard protects without the user's approval is in scope.
