"""NARCBench Core loader: 4-agent committees, 3 public rounds, then a final vote."""
from __future__ import annotations

import re
from pathlib import Path

from ..schema import Event, Label, Observation
from .narcbench import evaluated_run_ids, extract_brief, make_uid, pair_id, read_json, run_dir, split_message

TIER = "core"
AGENTS_PER_ROUND = 4
_OPTION = re.compile(r"^Option (\S+):", re.M)


def load_core_run(model: str, run_id: str, root: Path | None = None) -> tuple[Observation, Label]:
    d = run_dir(model, TIER, run_id, root)
    config = read_json(d / "run_config.json")
    results = read_json(d / "results.json")
    brief = extract_brief(read_json(d / "agent_prompts.json"))

    agents = tuple(sorted(results["final_texts"]))
    events = []
    for step, message in enumerate(results["public_messages"]):
        speaker, text = split_message(message)
        events.append(Event(step=step, round=step // AGENTS_PER_ROUND + 1, agent=speaker, text=text))
    _check_rounds(run_id, events, agents)

    uid = make_uid(model, TIER, run_id)
    observation = Observation(
        uid=uid,
        model=model,
        tier=TIER,
        brief=brief,
        agents=agents,
        options=tuple(_OPTION.findall(brief)),
        events=tuple(events),
        final_texts=dict(results["final_texts"]),
        votes=dict(results.get("votes", {})),
    )
    label = Label(
        uid=uid,
        run_id=run_id,
        pair_id=pair_id(run_id),
        model=model,
        tier=TIER,
        domain=config["scenario_domain"],
        mode=config["mode"],
        roles=dict(config["roles"]),
        coalition=tuple(config.get("coalition", ())),
        target_option=config.get("target_option"),
        fair_option=config.get("fair_option"),
        collusion_success=config.get("collusion_success"),
        colluder_voted_target=config.get("colluder_voted_target"),
        private_messages=tuple(results.get("private_messages", ())),
    )
    return observation, label


def _check_rounds(run_id: str, events: list[Event], agents: tuple[str, ...]) -> None:
    """Each round is a block of 4 messages in which every agent speaks once (order shuffled)."""
    for start in range(0, len(events), AGENTS_PER_ROUND):
        speakers = tuple(sorted(e.agent for e in events[start : start + AGENTS_PER_ROUND]))
        if speakers != agents:
            raise ValueError(f"{run_id}: round starting at step {start} has speakers {speakers}")


def load_core(model: str, root: Path | None = None) -> list[tuple[Observation, Label]]:
    return [load_core_run(model, run_id, root) for run_id in evaluated_run_ids(model, TIER, root)]
