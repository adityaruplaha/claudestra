---
name: fan-outs
description: Use before running many subagents (or many parallel sessions) on one job - projecting the usage and choosing the model, batching and isolating the work, recovering after a rate limit kills agents mid-batch, auditing when one output turns out to be fabricated, and settling it when two sessions find themselves on the same item.
---

# Running many agents on one job

How to run many subagents on one job: choosing the model, running the fan-out, recovering, auditing after a fabrication, and settling accidental forks. The user's choices that bear on it are in `claudestra preferences`; messaging other sessions is the `coordination` skill.

## Choosing the model

**Project the usage first:** how much each agent reads and reasons over, times how many agents there will be. Then follow the user's choice, `fan-out-model` in `claudestra preferences`:

- `cheaper`: a cheaper model for a heavy fan-out, the session's own for a light one. Say the projection and the choice before launching anything large.
- `same`: the session's own model, whatever the size.
- `ask`, or unchosen: say the projection and ask before launching anything large.

Keep the coordination that needs judgement on the session's own model: reading instructions and correspondence, deciding what a record should say, writing the final report. Do not discover a usage limit partway through: a rate limit kills every agent in flight at once.

## Running it

- **Announce the size of a large sweep before it starts.**
- **Small batches, not one item per agent.** One item per agent removes contamination between items but costs far more; batch a few.
- **Make isolation inside a batch explicit.** Each agent finishes and writes one item's output before opening the next input, never holds two inputs side by side, and never carries a number, a phrase or a figure from one to another.
- **Check quotations mechanically** where an input has a text layer: grep each quoted sentence against its source.
- **One writer per file.** When agents work on pieces of one document, each owns its own file and hands back a path or a block; the coordinating session splices them in. An agent that must check its piece in context builds a copy of the shared file in its own scratch space.
- **Measure what an agent hands back.** A claim that something fits, renders or passes is checked by rendering, running or measuring it.
- **Recover from a wipe through the filesystem.** A killed agent usually left part of its batch done: compare inputs with outputs and re-dispatch only the items with none.

## When a fabrication is found: audit, don't patch

Invented content in a record that goes to people is evidence that a process produced it, and the question becomes how much else it produced.

- **Audit all of the unit that failed**: every output of the batch, sweep or run that produced it.
- **Sample the rest at random**, with a fixed seed, so the selection is reproducible and shown to be random.
- **Add weighted picks on top, declared as such**: outputs with verbatim quotes, the extremes, any doubt about whose input is whose.
- **Look for unearned clearances too**, not only unearned faults: credit for something never done is as much a fabrication as blame for something never done.
- **Change nothing while auditing.** Establish the full extent, then make one corrective pass.

## Accidental forks of a session

A resumed window, a scheduled run or a reconnect can leave several sessions on the same item. Unless the user says otherwise, **the sessions settle it between themselves** and report the outcome, rather than asking the user to arbitrate:

- Message the other session with `SendMessage`, saying which paths you are writing and which subagents you have running.
- **The session with live subagents keeps the item.** The others stop their agents and go read-only on it; stopping can be undone, a lost update cannot.
- **Verify the other session's claims before standing down**: that its outputs exist and are complete.
- **Own your own overwrites.** If you overwrote another session's file without reading it first, say so and offer to restore it.
- **Check before writing** into an item's outputs; a fork does not announce itself, but `ListAgents` shows sessions on the same machine.

Cleaning up the forked transcripts afterwards is the `sessions` skill.
