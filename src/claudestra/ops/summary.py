"""`claudestra summary`: is a session finished? Read-only.

The prompts the user typed, how many messages arrived from elsewhere (peers, subagents' reports,
notifications, schedules, compaction summaries) without showing them as the user's, and Claude's last
reply, which is usually where a session says what is done and what is left open.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..claude_fs import ClaudeFS, origin_kind, prompt_text


@dataclass
class Summary:
    typed: list[str] = field(default_factory=list)
    relayed: dict[str, int] = field(default_factory=dict)
    last_reply: str = ""


def _relayed_kind(r: dict) -> str | None:
    """What a user record that the user did not type was: a summary, a meta record, or who sent it; None
    for a tool result, which is part of a turn rather than a message."""
    if r.get("isCompactSummary"):
        return "summary"
    if r.get("isMeta"):
        return "meta"
    c = r.get("message", {}).get("content") if isinstance(r.get("message"), dict) else None
    if isinstance(c, list) and any(isinstance(p, dict) and p.get("type") == "tool_result" for p in c):
        return None
    return origin_kind(r) if c else None


def summarise(fs: ClaudeFS, transcript: Path) -> Summary:
    out = Summary()
    for r in fs.records(transcript):
        if r.get("type") == "user":
            if (text := prompt_text(r)) is not None:
                out.typed.append(text)
            elif kind := _relayed_kind(r):
                out.relayed[kind] = out.relayed.get(kind, 0) + 1
        elif r.get("type") == "assistant" and isinstance(c := r.get("message", {}).get("content"), list):
            for p in c:
                if isinstance(p, dict) and p.get("type") == "text" and p.get("text", "").strip():
                    out.last_reply = p["text"].strip()
    return out
