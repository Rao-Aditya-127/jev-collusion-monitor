"""Data model. Monitors receive only `Observation`; `Label` is evaluation-side ground truth.

Keeping them as separate types (joined by an opaque `uid`) is what stops labels leaking into
monitor inputs: run_ids end in `__collusion` / `__control`, and roles / agent order reveal the
coalition, so none of those live on `Observation`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    step: int
    round: int
    agent: str
    text: str


@dataclass(frozen=True)
class Observation:
    uid: str
    model: str
    tier: str
    brief: str
    agents: tuple[str, ...]  # sorted alphabetically; source files list colluders first
    options: tuple[str, ...]
    events: tuple[Event, ...]
    final_texts: dict[str, str]
    votes: dict[str, str]  # may contain "?" for unparsed votes


@dataclass(frozen=True)
class Label:
    uid: str
    run_id: str
    pair_id: str
    model: str
    tier: str
    domain: str
    mode: str  # "collusion" | "control" | "implicit" (Transfer only: shared motive, no instruction to collude)
    roles: dict[str, str]
    coalition: tuple[str, ...]
    target_option: str | None
    fair_option: str | None
    collusion_success: bool | None
    colluder_voted_target: int | None
    private_messages: tuple[str, ...]
    sanitized_messages: int = 0  # public messages with self-leaked private notes stripped by the loader

    @property
    def is_collusion(self) -> bool:
        return self.mode == "collusion"
