"""Short lines from a model's reasoning as it streams, for whoever watches the turn.

Reasoning summaries arrive as deltas, usually as sections that open with a bold title
(``**Diagnosing workflow issues**`` then a paragraph). Each section's title is its line, sent the
moment the title closes; a section with no title gives its first sentence instead. A segment is the
reasoning between two visible moments (text or a tool call); ``reset`` starts the next."""

from __future__ import annotations

import re
from typing import List

MAX_CHARS = 120

_TITLE = re.compile(r"\*\*(.+?)\*\*")
_SENTENCE = re.compile(r"^(.+?[.!?])(?:\s|$)", re.S)


def _bounded(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= MAX_CHARS else line[:MAX_CHARS - 1].rstrip() + "…"


class ReasoningLines:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._text = ""
        self._titles = 0
        self._sentence_sent = False

    def feed(self, delta: str) -> List[str]:
        """The lines this delta completes."""
        self._text += delta
        titles = _TITLE.findall(self._text)
        if titles:
            new, self._titles = titles[self._titles:], len(titles)
            return [_bounded(t) for t in new if t.strip()]
        if self._sentence_sent or self._text.lstrip().startswith("*"):
            return []
        found = _SENTENCE.match(self._text.strip())
        if found is None:
            return []
        self._sentence_sent = True
        return [_bounded(found.group(1))]
