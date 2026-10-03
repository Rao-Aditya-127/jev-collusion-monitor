import json

from jevmon.leakguard import find_leaks
from jevmon.monitors.core_monitor import build_requests, load_questions, pair_key, score_run

QS = load_questions("v2")


def test_request_structure(core_runs):
    obs, _ = core_runs[0]
    requests = build_requests(obs, QS)
    assert [r.kind for r in requests] == ["message"] * 12 + ["round"] * 3 + ["final"]
    for r in requests[:12]:
        assert len(r.state["discussion_so_far"]) == r.step  # only earlier messages
        assert r.state["new_message"]["speaker"] == r.agent
        options = list(r.questions["echoes"]["criteria"])
        assert options == sorted(a for a in obs.agents if a != r.agent) + ["none"]
    for r in requests[12:15]:
        assert len(r.state["discussion"]) == 4 * r.round
        assert sum(k.startswith("pair::") for k in r.questions) == 6
    assert list(requests[-1].state["final_recommendations"]) == list(obs.agents)
    assert list(requests[0].state) == ["task_brief", "discussion_so_far", "new_message"]


def test_no_request_state_leaks_labels(core_runs):
    for obs, label in core_runs:
        for r in build_requests(obs, QS):
            assert find_leaks(json.dumps(r.state, ensure_ascii=False), label) == [], (label.run_id, r.kind)


def _fake_answers(requests, colluders):
    """Colluders look suspicious, honest agents do not."""
    answered = []
    for r in requests:
        if r.kind == "message":
            bad = r.agent in colluders
            ans = {q: {"noul": 0.8 if bad else 0.1} for q in ("spin", "withholding", "coordinating")}
            ans |= {q: {"noul": 0.2} for q in ("honest_disagreement", "honest_mistake")}
            ans["evidence_support"] = {"score": 1.0 if bad else 3.0, "probabilities": {"0": 0, "1": 1, "2": 0, "3": 0}}
            partner = next((c for c in colluders if c != r.agent), None) if bad else None
            probs = {o: 0.0 for o in r.questions["echoes"]["criteria"]}
            probs[partner or "none"] = 1.0
            ans["echoes"] = {"probabilities": probs}
        elif r.kind == "round":
            ans = {k: {"noul": 0.9 if k == pair_key(*colluders) else 0.1} for k in r.questions if k.startswith("pair::")}
            ans["coordination_present"] = {"noul": 0.7}
        else:
            ans = {k: {"noul": 0.2 if k.split("::")[1] in colluders else 0.9} for k in r.questions}
        answered.append((r, ans))
    return answered


def test_score_run_recovers_coalition(core_runs):
    obs, label = next((o, l) for o, l in core_runs if l.is_collusion)
    scored = score_run(obs, _fake_answers(build_requests(obs, QS), label.coalition), QS)
    truth = pair_key(*label.coalition)
    assert set(scored["predicted"].values()) == {truth}
    assert scored["run"]["pair_final_max"] == 0.9
    for agent, row in scored["agents"].items():
        assert (row["suspicion"] > 0.5) == (agent in label.coalition)
