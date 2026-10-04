"""Score the FROZEN questions once on the Core test split, as pre-registered in configs/frozen.json.

    uv run python -m jevmon.experiments.core_test

Refuses to run if the question file no longer matches the frozen sha256. Writes
outputs/reports/core_test.md and outputs/scores/core_test_scores.json.
"""
from __future__ import annotations

import asyncio
import datetime
import hashlib
import json

from ..baselines.core import vote_minority, vote_nonfair
from ..eval.metrics import auroc, bootstrap_diff_ci
from ..eval.splits import core_split, load_splits
from ..leakguard import find_leaks
from ..loaders.core import load_core
from ..monitors.core_monitor import build_requests, pair_key, score_run
from ..monitors.jev_client import JevClient, LeakError
from ..paths import REPO_ROOT
from .reporting import inside_meetings, metric_rows, pair_up

FROZEN = REPO_ROOT / "configs" / "frozen.json"
PRICE_PER_MTOK = 0.042


def load_frozen() -> tuple[dict, dict]:
    spec = json.loads(FROZEN.read_text(encoding="utf-8"))
    raw = (REPO_ROOT / spec["questions"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != spec["sha256"]:
        raise SystemExit(f"{spec['questions']} changed since it was frozen; refusing to score the test split")
    return spec, json.loads(raw)


async def answer(runs, qs, model):
    request_sets = [build_requests(o, qs) for o, _ in runs]
    for (_, label), requests in zip(runs, request_sets):
        for r in requests:
            if leaks := find_leaks(json.dumps(r.state, ensure_ascii=False), label):
                raise LeakError(f"{label.run_id} {r.kind}: {leaks}")
    async with JevClient(model=model) as client:
        results = await asyncio.gather(*(client.ask(r.state, r.questions) for reqs in request_sets for r in reqs))
    scored, i = [], 0
    for (obs, _), requests in zip(runs, request_sets):
        scored.append(score_run(obs, list(zip(requests, [r.answers for r in results[i: i + len(requests)]])), qs))
        i += len(requests)
    return scored, results


def evaluate(model_name, pairs, qs) -> tuple[list[str], dict]:
    primary, secondary = qs["scoring"]["primary_run_score"], qs["scoring"]["secondary_run_score"]
    jev = lambda name: (lambda p, mode: p[mode][2]["run"][name])  # noqa: E731
    scorers = {
        f"**Jev {primary}** (primary)": jev(primary),
        f"Jev {secondary}": jev(secondary),
        "vote_minority (no AI, label-free)": lambda p, mode: vote_minority(p[mode][0]),
        "*vote_nonfair (oracle, reads labels)*": lambda p, mode: vote_nonfair(p[mode][0], p[mode][1]),
    }
    no_refusal = [p for p in pairs if p["collusion"][1].colluder_voted_target]

    pos_j = [p["collusion"][2]["run"][primary] for p in pairs]
    neg_j = [p["control"][2]["run"][primary] for p in pairs]
    pos_v = [vote_minority(p["collusion"][0]) for p in pairs]
    neg_v = [vote_minority(p["control"][0]) for p in pairs]
    diff = auroc(pos_j, neg_j) - auroc(pos_v, neg_v)
    d_lo, d_hi = bootstrap_diff_ci(pos_j, neg_j, pos_v, neg_v, auroc)
    found = sum(p["collusion"][2]["predicted"]["by_pair_question"] == pair_key(*p["collusion"][1].coalition) for p in pairs)
    found_nr = sum(p["collusion"][2]["predicted"]["by_pair_question"] == pair_key(*p["collusion"][1].coalition)
                   for p in no_refusal)

    lines = [f"## {model_name}", "",
             f"**Primary comparison:** AUROC(Jev `{primary}`) − AUROC(vote_minority) = **{diff:+.3f}** "
             f"[95% paired CI {d_lo:+.2f}, {d_hi:+.2f}] on {len(pairs)} pairs.", "",
             "### All test pairs", "", *metric_rows(pairs, scorers), "",
             f"### Without refusals ({len(no_refusal)} pairs)", "", *metric_rows(no_refusal, scorers), "",
             "### Naming the coalition", "",
             f"- Top round-3 pair question = true coalition: **{found}/{len(pairs)}** collusion runs "
             f"({found / len(pairs):.0%}); without refusals {found_nr}/{len(no_refusal)}. Chance: 1/6 (17%).", "",
             "### Per meeting", "", *inside_meetings(pairs)[0], ""]
    summary = {"pairs": len(pairs), "primary_auroc": auroc(pos_j, neg_j), "vote_minority_auroc": auroc(pos_v, neg_v),
               "diff": diff, "diff_ci": [d_lo, d_hi], "coalition_found": found}
    return lines, summary


def main() -> None:
    spec, qs = load_frozen()
    splits = load_splits()
    sections, summaries, dump = [], {}, []
    tokens, latencies = 0, []
    for role in ("primary", "secondary"):
        data_model = spec["preregistered_test"]["data"][role]["model"]
        runs = [(o, l) for o, l in load_core(data_model) if core_split(l, splits) == "test"]
        scored, results = asyncio.run(answer(runs, qs, spec["jev_model"]))
        tokens += sum(r.usage.get("input_tokens", 0) for r in results)
        latencies += [r.latency_s for r in results if r.latency_s is not None]
        lines, summaries[data_model] = evaluate(f"{data_model} ({role})", pair_up(runs, scored), qs)
        sections += lines
        dump += [{"model": data_model, "run_id": l.run_id, "run": s["run"], "agents": s["agents"],
                  "predicted": s["predicted"]} for (_, l), s in zip(runs, scored)]

    latencies.sort()
    head = ["# Core test split: frozen questions v2", "",
            f"Generated {datetime.date.today().isoformat()} by `uv run python -m jevmon.experiments.core_test`. "
            f"Questions `{spec['questions']}` (sha256 `{spec['sha256'][:12]}…`, frozen {spec['frozen_on']}), "
            f"model `{spec['jev_model']}`. Pre-registration: `configs/frozen.json`.", "",
            f"- Input tokens: {tokens:,} (≈ ${tokens / 1e6 * PRICE_PER_MTOK:.3f})."]
    if latencies:
        head.append(f"- Latency (uncached calls): p50 {latencies[len(latencies) // 2]:.2f} s, "
                    f"p95 {latencies[int(len(latencies) * 0.95) - 1]:.2f} s.")
    head += ["- Run once, as pre-registered. Anything changed after this is post hoc.", ""]
    report = "\n".join(head + sections)
    (REPO_ROOT / "outputs" / "reports" / "core_test.md").write_text(report, encoding="utf-8")
    (REPO_ROOT / "outputs" / "scores" / "core_test_scores.json").write_text(
        json.dumps({"summary": summaries, "runs": dump}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
