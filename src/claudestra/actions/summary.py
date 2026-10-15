"""`claudestra summary`: is a session finished? Its typed prompts, what was relayed, and its last reply."""

from __future__ import annotations

from ..caller import Refused
from ..ops import summary as summary_ops
from .base import ReadOnlyAction


class Summary(ReadOnlyAction):
    verb = "summarise"

    def __init__(self, session, reply_chars: int = 1500):
        super().__init__(session)
        self.reply_chars = reply_chars

    def check(self) -> None:
        if self.object.transcript is None:
            raise Refused(f"{self.object.id} has no single transcript on this machine")

    def run(self) -> summary_ops.Summary:
        return summary_ops.summarise(self.context.fs, self.object.transcript)
