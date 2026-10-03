"""Shared NARCBench helpers: evaluated run list, file access and label-free parsing."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ..paths import data_root

MODELS = ("qwen3_32b", "gpt_oss_20b")

# Text before the first of these markers is the scenario brief, identical for every agent and for
# both runs of a pair (checked 30 Sep 2026 on Core and on Transfer cicd/code_review/pump_dump/rag/
# research; news needs STORY DRAFT SO FAR). Stego briefs must come from hand_results instead.
BRIEF_CUT = re.compile(
    r"PRIVATE COORDINATION|FULL DISCUSSION HISTORY|DISCUSSION HISTORY|PIPELINE OUTPUT SO FAR|STORY DRAFT SO FAR"
)
_MESSAGE = re.compile(r"\[(.+?)\]: (.*)", re.S)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def evaluated_run_ids(model: str, tier: str, root: Path | None = None) -> list[str]:
    """Runs the paper evaluated: the run_ids in the activations metadata.

    The scenario folders hold extra, unpaired runs (e.g. Qwen Core has 50 + 50 on disk, 31 + 31 evaluated).
    """
    meta = read_json((root or data_root()) / "activations" / model / tier / "metadata_gen.json")
    return sorted({row["run_id"] for row in meta})


def run_dir(model: str, tier: str, run_id: str, root: Path | None = None) -> Path:
    return (root or data_root()) / "scenarios" / model / tier / run_id


def make_uid(model: str, tier: str, run_id: str) -> str:
    """Opaque join key. run_ids end in __collusion / __control, so they never travel with observations."""
    return hashlib.sha256(f"{model}/{tier}/{run_id}".encode()).hexdigest()[:16]


def pair_id(run_id: str) -> str:
    return run_id.rsplit("__", 1)[0]


def split_message(message: str) -> tuple[str, str]:
    match = _MESSAGE.match(message)
    if not match:
        raise ValueError(f"unparseable message: {message[:80]!r}")
    return match.group(1), match.group(2)


def extract_brief(agent_prompts: list[dict]) -> str:
    """First public-channel prompt of any agent, cut before the private block or the history.

    Deliberately does not pick the agent by role: that would read a label.
    """
    first = next(p for p in agent_prompts if p["channel"] == "public")
    return BRIEF_CUT.split(first["user_prompt"])[0].strip()
