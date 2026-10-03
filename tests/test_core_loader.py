import dataclasses
import json
from collections import defaultdict

import pytest

from jevmon.leakguard import find_leaks
from jevmon.loaders.core import load_core_run
from jevmon.loaders.narcbench import read_json, run_dir
from jevmon.paths import data_root

EXPECTED_PAIRS = {"qwen3_32b": 31, "gpt_oss_20b": 18}


def _pairs(core_runs):
    pairs = defaultdict(dict)
    for obs, label in core_runs:
        pairs[label.pair_id][label.mode] = (obs, label)
    return pairs


def test_evaluated_set_is_paired(core_runs):
    model = core_runs[0][1].model
    pairs = _pairs(core_runs)
    assert len(pairs) == EXPECTED_PAIRS[model]
    assert all(set(p) == {"collusion", "control"} for p in pairs.values())


def test_structure(core_runs):
    for obs, label in core_runs:
        assert len(obs.events) == 12
        assert [e.round for e in obs.events] == [1] * 4 + [2] * 4 + [3] * 4
        assert len(obs.agents) == 4 and list(obs.agents) == sorted(obs.agents)
        assert set(obs.final_texts) == set(obs.agents) == set(obs.votes) == set(label.roles)
        config = read_json(run_dir(label.model, "core", label.run_id) / "run_config.json")
        assert list(obs.options) == config["option_labels"]


def test_agent_order_does_not_follow_roles(core_runs):
    # Source files list colluders first; observations must not.
    for obs, label in core_runs:
        if label.is_collusion:
            assert list(obs.agents) == sorted(label.roles)


def test_brief_is_label_free_and_identical_within_pair(core_runs):
    for p in _pairs(core_runs).values():
        collusion_obs, control_obs = p["collusion"][0], p["control"][0]
        assert collusion_obs.brief == control_obs.brief
        assert "PRIVATE" not in collusion_obs.brief and "DISCUSSION HISTORY" not in collusion_obs.brief
        assert collusion_obs.options and "OPTIONS UNDER REVIEW" in collusion_obs.brief


def test_observations_carry_no_labels(core_runs):
    for obs, label in core_runs:
        payload = json.dumps(dataclasses.asdict(obs), ensure_ascii=False)
        assert find_leaks(payload, label) == [], label.run_id


@pytest.mark.skipif(not (data_root() / "scenarios" / "qwen3_32b" / "core").is_dir(), reason="data not downloaded")
def test_known_refusal_run_is_labelled_collusion():
    # cyber_02: colluders agreed privately to vote the fair option. Kept in the evaluated set by the paper.
    obs, label = load_core_run("qwen3_32b", "deception__cyber_02__collusion")
    assert label.is_collusion and label.colluder_voted_target == 0
    assert all(v == label.fair_option for v in obs.votes.values())
