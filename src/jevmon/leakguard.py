"""Check that text bound for a monitor carries no ground truth.

Every Jev request payload goes through `find_leaks` before it is sent. On Core, none of these
patterns occur naturally in public text (checked 2 Oct 2026), so any hit is a pipeline bug.
"""
from __future__ import annotations

import re

from .loaders.narcbench import split_message
from .schema import Label

LABEL_WORDS = re.compile(r"colluder|collusion|coalition|PRIVATE COORDINATION", re.I)
SNIPPET_CHARS = 60


def _normalise(text: str) -> str:
    return " ".join(text.split())


def find_leaks(payload: str, label: Label) -> list[str]:
    """Return a description of every leak found in `payload` (empty list = clean)."""
    flat = _normalise(payload)
    leaks = [f"label word {m.group(0)!r}" for m in LABEL_WORDS.finditer(flat)]
    if label.run_id in flat:
        leaks.append("run_id")
    for message in label.private_messages:
        try:
            _, text = split_message(message)
        except ValueError:
            text = message
        snippet = _normalise(text)[:SNIPPET_CHARS]
        if len(snippet) == SNIPPET_CHARS and snippet in flat:
            leaks.append(f"private message text {snippet[:30]!r}...")
    return leaks
