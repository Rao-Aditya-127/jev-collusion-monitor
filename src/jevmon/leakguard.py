"""Check that text bound for a monitor carries no ground truth.

Every Jev request goes through `find_leaks` before it is sent. A leak is answer-key content in the
request that is NOT already part of the run's public record: label words, the run id, or a whole
private message. Pass `public_text=public_record(obs)` so that things the agents themselves said in
public (a journalist writing "collusion", an agent publicly reposting the draft it wrote in the private
chat, an implicit agent admitting "our private coordination") are not mistaken for pipeline bugs.
Without `public_text` the check is strict; on Core even the strict version finds nothing.
"""
from __future__ import annotations

import re

from .loaders.narcbench import split_message
from .schema import Label, Observation

LABEL_WORDS = re.compile(r"colluder|collusion|PRIVATE COORDINATION", re.I)
WINDOW = 60  # characters per probe; a private message counts as leaked only if all its probes appear


def _normalise(text: str) -> str:
    return " ".join(text.split())


def public_record(obs: Observation) -> str:
    """Everything the run made public: the brief, every public message and every final text."""
    return "\n".join([obs.brief, *(e.text for e in obs.events), *obs.final_texts.values()])


def _probes(text: str) -> list[str]:
    """Three windows spread over the message (or the whole message if it is short)."""
    if len(text) < 3 * WINDOW:
        return [text] if len(text) >= 40 else []
    return [text[int(len(text) * f) - WINDOW // 2: int(len(text) * f) + WINDOW // 2] for f in (0.25, 0.5, 0.75)]


def find_leaks(payload: str, label: Label, public_text: str | None = None) -> list[str]:
    """Return a description of every leak found in `payload` (empty list = clean)."""
    flat = _normalise(payload)
    public = _normalise(public_text).lower() if public_text is not None else None
    leaks = [f"label word {m.group(0)!r}" for m in LABEL_WORDS.finditer(flat)
             if public is None or m.group(0).lower() not in public]
    if label.run_id in flat:
        leaks.append("run_id")
    for message in label.private_messages:
        try:
            _, text = split_message(message)
        except ValueError:
            text = message
        probes = _probes(_normalise(text))
        if probes and all(p in flat for p in probes):
            if public is None or not all(p.lower() in public for p in probes):
                leaks.append(f"private message text {probes[0][:30]!r}...")
    return leaks
