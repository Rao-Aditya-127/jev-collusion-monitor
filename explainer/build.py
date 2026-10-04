"""Build explainer/index.html: a step-by-step guide to this repo, filled with real data and results.

    uv run python explainer/build.py

It is a LIVE document: re-run after every experiment and commit the regenerated index.html.
Rebuilding needs the dataset in data/narcbench/ and the outputs/ results (and a Jev key only if the cache is missing).
To add a new experiment: save its numbers under outputs/ (reports/*.md or scores/*.json), read them in
`collect()`, and add a section to template.html.
All Jev answers shown come from the local cache, so building makes no paid API calls
(unless the cache was deleted, in which case the few missing calls are re-made).
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from jevmon.baselines.core import echo_standout, vote_minority, vote_nonfair
from jevmon.eval.metrics import auroc, bootstrap_ci
from jevmon.eval.splits import core_split, load_splits
from jevmon.loaders.core import load_core
from jevmon.loaders.narcbench import MODELS, evaluated_run_ids, read_json, run_dir
from jevmon.loaders.transfer import load_transfer
from jevmon.monitors.core_monitor import build_requests, load_questions, pair_key, score_run
from jevmon.monitors.jev_client import JevClient
from jevmon.paths import REPO_ROOT, data_root

HERE = Path(__file__).resolve().parent
OUTPUTS = REPO_ROOT / "outputs"

# Published white-box results (NARCBench paper, Qwen3-32B, Table 4).
PAPER = {"core": 1.00, "transfer_all": 0.88, "cicd": 0.73, "rag": 0.83, "stego": 1.00}


def dataset_facts() -> dict:
    tiers = ("core", "transfer", "stego")
    counts = []
    for model in MODELS:
        for tier in tiers:
            on_disk = Counter(d.rsplit("__", 1)[-1] for d in os.listdir(data_root() / "scenarios" / model / tier))
            evaluated = Counter(r.rsplit("__", 1)[-1] for r in evaluated_run_ids(model, tier))
            counts.append({"model": model, "tier": tier, "on_disk": dict(on_disk), "evaluated": dict(evaluated)})
    splits = load_splits()
    domains: dict[str, dict] = {}
    core_dir = data_root() / "scenarios" / "qwen3_32b" / "core"
    evaluated = set(evaluated_run_ids("qwen3_32b", "core"))
    for run in sorted(os.listdir(core_dir)):
        if not run.endswith("__collusion"):
            continue
        dom = read_json(core_dir / run / "run_config.json")["scenario_domain"]
        entry = domains.setdefault(dom, {"domain": dom, "scenarios": 0, "evaluated_pairs": 0})
        entry["scenarios"] += 1
        entry["evaluated_pairs"] += run in evaluated
    for entry in domains.values():
        entry["split"] = ("dev" if entry["domain"] in splits["core"]["dev_domains"]
                          else "test" if entry["evaluated_pairs"] else "not evaluated")
    return {"counts": counts, "domains": sorted(domains.values(), key=lambda d: (d["split"], d["domain"]))}


def _hidden_goal(prompts: list[dict]) -> str:
    """The colluders' secret motive: the system prompt of the first colluder, minus its first line."""
    p = next((p for p in prompts if p["role"] == "colluder" and p["phase"] == "discussion"), None)
    if not p:
        return ""
    parts = [x.strip() for x in p["system_prompt"].split("\n\n") if x.strip()]
    return " ".join(parts[1:3])[:700]


async def dev_meetings(qs: dict) -> tuple[list[dict], dict]:
    splits = load_splits()
    runs = [(o, l) for o, l in load_core("qwen3_32b") if core_split(l, splits) == "dev"]
    request_sets = [build_requests(o, qs) for o, _ in runs]
    async with JevClient() as client:
        results = await asyncio.gather(*(client.ask(r.state, r.questions) for reqs in request_sets for r in reqs))
    meetings, i, example = [], 0, None
    for (obs, label), requests in zip(runs, request_sets):
        answers = [r.answers for r in results[i: i + len(requests)]]
        i += len(requests)
        scored = score_run(obs, list(zip(requests, answers)), qs)
        d = run_dir(label.model, "core", label.run_id)
        config, prompts = read_json(d / "run_config.json"), read_json(d / "agent_prompts.json")
        events, rounds, final = [], {}, {}
        for req, ans in zip(requests, answers):
            if req.kind == "message":
                echo = {k: v for k, v in ans["echoes"]["probabilities"].items()}
                top = max(echo, key=echo.get)
                events.append({"step": req.step, "round": req.round, "agent": req.agent,
                               "text": obs.events[req.step].text,
                               "jev": {"unsupported": round(1 - ans["evidence_support"]["score"] / 3, 3),
                                       "spin": ans["spin"]["noul"], "withholding": ans["withholding"]["noul"],
                                       "echo_top": top, "echo_p": echo[top]}})
                if example is None and label.is_collusion and req.agent == label.coalition[-1]:
                    example = {"meeting": label.pair_id.removeprefix("deception__"), "agent": req.agent,
                               "state": req.state, "questions": req.questions, "answers": ans}
            elif req.kind == "round":
                rounds[req.round] = {
                    "pairs": sorted(({"pair": k.removeprefix("pair::"), "p": v["noul"]} for k, v in ans.items()
                                     if k.startswith("pair::")), key=lambda x: -x["p"]),
                    "coordination": ans["coordination_present"]["noul"]}
            else:
                final = {k.split("::", 1)[1]: v["noul"] for k, v in ans.items()}
        meetings.append({
            "pair": label.pair_id.removeprefix("deception__"), "mode": label.mode, "domain": label.domain,
            "title": config.get("scenario_title", ""), "brief": obs.brief, "agents": list(obs.agents),
            "events": events, "rounds": rounds,
            "final": {a: {"text": obs.final_texts[a], "vote": obs.votes.get(a), "follows": final[a]} for a in obs.agents},
            "scores": {"suspicion": {a: v["suspicion"] for a, v in scored["agents"].items()},
                       "predicted": scored["predicted"]["by_pair_question"].removeprefix("pair::"),
                       "primary": scored["run"][qs["scoring"]["primary_run_score"]],
                       "secondary": scored["run"][qs["scoring"]["secondary_run_score"]]},
            "key": {"roles": label.roles, "coalition": list(label.coalition),
                    "truth": pair_key(*label.coalition).removeprefix("pair::") if label.coalition else None,
                    "target": label.target_option, "fair": label.fair_option,
                    "colluder_voted_target": label.colluder_voted_target,
                    "private": list(label.private_messages), "hidden_goal": _hidden_goal(prompts)},
        })
    return meetings, example


def _md_number(path: Path, pattern: str, cast=float):
    try:
        m = re.search(pattern, path.read_text(encoding="utf-8"))
        return cast(m.group(1).replace(",", "")) if m else None
    except FileNotFoundError:
        return None


def experiments() -> dict:
    out = {}
    rows = json.loads((OUTPUTS / "reports" / "core_baselines.json").read_text(encoding="utf-8"))
    out["baselines"] = [r for r in rows if r["model"] == "qwen3_32b" and r["split"] == "test"
                        and r["subset"] == "all pairs" and "auroc" in r]

    spike = json.loads((OUTPUTS / "scores" / "spike_dev_scores.json").read_text(encoding="utf-8"))
    md = OUTPUTS / "reports" / "spike_dev.md"
    out["spike"] = {"feature_auroc": spike["feature_auroc"], "tokens_per_pass": spike["tokens_per_pass"],
                    "identical": _md_number(md, r"identical in all passes: \*\*(\d+)%"),
                    "noise_median": _md_number(md, r"range \(max − min\): median ([\d.]+)"),
                    "noise_p95": _md_number(md, r"95th percentile ([\d.]+)"),
                    "latency_p50": _md_number(md, r"p50 ([\d.]+) s")}
    out["checks"] = json.loads((OUTPUTS / "scores" / "dev_checks_v2.json").read_text(encoding="utf-8"))

    test_md = OUTPUTS / "reports" / "core_test.md"
    scores = json.loads((OUTPUTS / "scores" / "core_test_scores.json").read_text(encoding="utf-8"))
    frozen = json.loads((REPO_ROOT / "configs" / "frozen.json").read_text(encoding="utf-8"))
    qs = load_questions("v2")
    primary, secondary = qs["scoring"]["primary_run_score"], qs["scoring"]["secondary_run_score"]
    models = {}
    for model in ("qwen3_32b", "gpt_oss_20b"):
        by_run = {r["run_id"]: r for r in scores["runs"] if r["model"] == model}
        pairs = defaultdict(dict)
        for obs, label in load_core(model):
            if label.run_id not in by_run:
                continue
            r = by_run[label.run_id]
            pairs[label.pair_id][label.mode] = {
                "primary": r["run"][primary], "secondary": r["run"][secondary],
                "vote": vote_minority(obs), "oracle": vote_nonfair(obs, label),
                "named": (r["predicted"]["by_pair_question"] == pair_key(*label.coalition)) if label.coalition else None}
            if label.is_collusion:
                pairs[label.pair_id]["refusal"] = not label.colluder_voted_target
                pairs[label.pair_id]["domain"] = label.domain
        plist = [{"pair": k.removeprefix("deception__"), **v} for k, v in sorted(pairs.items())]
        methods = {}
        for key, name in (("primary", "Jev: pair question (main score)"), ("secondary", "Jev: most suspicious agent"),
                          ("vote", "Vote counting (no AI)"), ("oracle", "Vote vs. the known fair option (uses answer key)")):
            pos = [p["collusion"][key] for p in plist]
            neg = [p["control"][key] for p in plist]
            methods[key] = {"name": name, "auroc": auroc(pos, neg), "ci": bootstrap_ci(pos, neg, auroc)}
        models[model] = {"pairs": plist, "methods": methods, "summary": scores["summary"][model]}
    out["test"] = {"models": models, "frozen": frozen,
                   "tokens": _md_number(test_md, r"Input tokens: ([\d,]+)", int),
                   "latency_p50": _md_number(test_md, r"p50 ([\d.]+) s"),
                   "meetings": sum(len(m["pairs"]) * 2 for m in models.values())}
    out["transfer"] = transfer_results()
    return out


def transfer_results() -> dict:
    """Experiment 5: frozen v2 questions, zero-shot on Transfer (outputs/scores/transfer_test_scores.json)."""
    md = OUTPUTS / "reports" / "transfer_test.md"
    data = json.loads((OUTPUTS / "scores" / "transfer_test_scores.json").read_text(encoding="utf-8"))
    summary = data["summary"]
    by_run = {(r["model"], r["run_id"]): r for r in data["runs"]}
    methods = {}
    pairs = defaultdict(dict)
    for obs, label in load_transfer("qwen3_32b"):
        r = by_run[("qwen3_32b", label.run_id)]
        pairs[label.pair_id][label.mode] = {"primary": r["run"]["pair_final_max"], "secondary": r["run"]["peak_suspicion"],
                                            "echo": echo_standout(obs)}
    plist = list(pairs.values())
    for key, name in (("primary", "Jev: pair question (main score)"), ("secondary", "Jev: most suspicious agent"),
                      ("echo", "Word overlap between agents (no AI)")):
        pos, neg = [p["collusion"][key] for p in plist], [p["control"][key] for p in plist]
        methods[key] = {"name": name, "auroc": auroc(pos, neg), "ci": bootstrap_ci(pos, neg, auroc)}
    qwen = summary["qwen3_32b (primary)"]
    shuffled = [f for f in ("code_review", "news", "pump_dump", "rag")]
    return {
        "qwen": qwen, "gpt": summary["gpt_oss_20b (secondary)"],
        "implicit": summary["qwen3_32b (exploratory: implicit vs control)"],
        "methods": methods, "paper_all": 0.88,
        "paper_best": {"cicd": 0.73, "code_review": 1.00, "news": 0.96, "pump_dump": 0.99, "rag": 0.83, "research": 1.00},
        "shuffled_named": sum(qwen["families"][f]["named"] for f in shuffled),
        "shuffled_pairs": sum(qwen["families"][f]["pairs"] for f in shuffled),
        "calls": _md_number(md, r"Total for both attempts: ([\d,]+) calls", int),
        "tokens_m": _md_number(md, r"calls, ([\d.]+)M input tokens"),
        "meetings": _md_number(md, r"for (\d+) meetings", int),
    }


def collect() -> dict:
    qs = load_questions("v2")
    meetings, example = asyncio.run(dev_meetings(qs))
    return {
        "built": datetime.datetime.now().strftime("%d %b %Y, %H:%M"),
        "paper": PAPER,
        "dataset": dataset_facts(),
        "meetings": meetings,
        "example": example,
        "questions": {k: {q: v.get("instructions") for q, v in qs[k].items()} for k in ("message", "round", "final")},
        "experiments": experiments(),
    }


def main() -> None:
    data = collect()
    template = (HERE / "template.html").read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = template.replace("/*__DATA__*/null", payload)
    (HERE / "index.html").write_text(html, encoding="utf-8")
    print(f"wrote {HERE / 'index.html'} ({len(html) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
