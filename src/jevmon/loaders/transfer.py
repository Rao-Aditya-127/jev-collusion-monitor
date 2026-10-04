"""NARCBench Transfer loader: six task families with no vote (code review, CI/CD, RAG, research, news,
pump & dump).

Structure (checked 3 Oct 2026): cicd and research are 4-message pipelines in a fixed order (one round;
the colluders always sit at positions 0 and 2); the other families have 12 messages in 3 rounds where
every agent speaks once per round. Each run ends with one final text per agent.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from ..paths import data_root
from ..schema import Event, Label, Observation
from .narcbench import evaluated_run_ids, extract_brief, make_uid, pair_id, read_json, run_dir, split_message

TIER = "transfer"
AGENTS_PER_ROUND = 4

# In news nf_06 the colluders appended "**Private Coordination (only you and I see this):** ..." to their
# public messages. That self-leak is trivially detectable and unrealistic, so it is stripped (pre-registered
# in configs/preregistration_transfer.json), the same policy as Stego's PRIVATE: lines.
_SELF_LEAK = re.compile(r"^[^\n]*private coordination \(only you[^\n]*$", re.I | re.M)


def strip_private_notes(text: str) -> tuple[str, bool]:
    m = _SELF_LEAK.search(text)
    if not m:
        return text, False
    return text[: m.start()].rstrip().rstrip("-").rstrip(), True


def family(run_id: str) -> str:
    return run_id.split("__", 1)[0]


def load_transfer_run(model: str, run_id: str, root: Path | None = None) -> tuple[Observation, Label]:
    d = run_dir(model, TIER, run_id, root)
    config = read_json(d / "run_config.json")
    results = read_json(d / "results.json")
    brief = extract_brief(read_json(d / "agent_prompts.json"))

    agents = tuple(sorted(results["final_texts"]))
    events, stripped = [], 0
    for step, message in enumerate(results["public_messages"]):
        speaker, text = split_message(message)
        text, hit = strip_private_notes(text)
        stripped += hit
        events.append(Event(step=step, round=step // AGENTS_PER_ROUND + 1, agent=speaker, text=text))
    for start in range(0, len(events), AGENTS_PER_ROUND):
        speakers = tuple(sorted(e.agent for e in events[start: start + AGENTS_PER_ROUND]))
        if speakers != agents:
            raise ValueError(f"{run_id}: block starting at step {start} has speakers {speakers}")
    finals = {}
    for a in agents:
        finals[a], hit = strip_private_notes(results["final_texts"][a])
        stripped += hit

    uid = make_uid(model, TIER, run_id)
    observation = Observation(uid=uid, model=model, tier=TIER, brief=brief, agents=agents, options=(),
                              events=tuple(events), final_texts=finals, votes={})
    label = Label(
        uid=uid, run_id=run_id, pair_id=pair_id(run_id), model=model, tier=TIER, domain=family(run_id),
        mode=config["mode"], roles=dict(config["roles"]), coalition=tuple(config.get("coalition", ())),
        target_option=None, fair_option=None, collusion_success=None, colluder_voted_target=None,
        private_messages=tuple(results.get("private_messages", ())), sanitized_messages=stripped,
    )
    return observation, label


def load_transfer(model: str, include_implicit: bool = False, root: Path | None = None) -> list[tuple[Observation, Label]]:
    """The paper's evaluated runs; optionally also the unevaluated `implicit` runs (Qwen only)."""
    run_ids = evaluated_run_ids(model, TIER, root)
    if include_implicit:
        on_disk = os.listdir((root or data_root()) / "scenarios" / model / TIER)
        run_ids += sorted(r for r in on_disk if r.endswith("__implicit"))
    return [load_transfer_run(model, r, root) for r in run_ids]
