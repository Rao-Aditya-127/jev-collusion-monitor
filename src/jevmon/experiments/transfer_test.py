"""Score the FROZEN v2 questions zero-shot on Transfer, as pre-registered in configs/preregistration_transfer.json.

    uv run python -m jevmon.experiments.transfer_test

Refuses to run if the question file changed since the freeze. Writes outputs/reports/transfer_test.md
and outputs/scores/transfer_test_scores.json.
"""
from __future__ import annotations

import asyncio
import datetime
import json
from collections import defaultdict

from ..baselines.core import echo_max, echo_standout
from ..eval.metrics import auroc, bootstrap_ci, bootstrap_diff_ci
from ..leakguard import find_leaks, public_record
from ..loaders.transfer import load_transfer
from ..monitors.core_monitor import build_requests, pair_key, score_run
from ..monitors.jev_client import JevClient, LeakError
from ..paths import REPO_ROOT
from .core_test import load_frozen
from .reporting import inside_meetings, metric_rows

PREREG = REPO_ROOT / "configs" / "preregistration_transfer.json"
PRICE_PER_MTOK = 0.042
FAMILIES = {"cicd": "CI/CD pipeline", "code_review": "Code review", "news": "News framing",
            "pump_dump": "Pump & dump", "rag": "RAG poisoning", "research": "Research pipeline"}
PAPER_BEST = {"cicd": 0.73, "code_review": 1.00, "news": 0.96, "pump_dump": 0.99, "rag": 0.83, "research": 1.00}
PAPER_ALL = 0.88


def load_prereg() -> tuple[dict, dict]:
    frozen, qs = load_frozen()
    pre = json.loads(PREREG.read_text(encoding="utf-8"))
    if pre["questions_sha256"] != frozen["sha256"]:
        raise SystemExit("pre-registration and freeze disagree on the question file")
    return pre, qs


async def answer(runs, qs, model):
    request_sets = [build_requests(o, qs) for o, _ in runs]
    publics = [public_record(o) for o, _ in runs]
    for (_, label), requests, public in zip(runs, request_sets, publics):
        for r in requests:
            if leaks := find_leaks(json.dumps(r.state, ensure_ascii=False), label, public):
                raise LeakError(f"{label.run_id} {r.kind}: {leaks}")
    async with JevClient(model=model) as client:
        results = await asyncio.gather(*(client.ask(r.state, r.questions, public)
                                         for reqs, public in zip(request_sets, publics) for r in reqs))
    scored, i = [], 0
    for (obs, _), requests in zip(runs, request_sets):
        scored.append(score_run(obs, list(zip(requests, [r.answers for r in results[i: i + len(requests)]])), qs))
        i += len(requests)
    return scored, results


def make_pairs(runs, scored, positive: str = "collusion") -> list[dict]:
    """Pairs of (positive run, its control twin); `positive` is "collusion" or "implicit"."""
    by_pair = defaultdict(dict)
    for (obs, label), s in zip(runs, scored):
        if label.mode in (positive, "control"):
            by_pair[label.pair_id]["collusion" if label.mode == positive else "control"] = (obs, label, s)
    return [by_pair[k] for k in sorted(by_pair) if len(by_pair[k]) == 2]


def _named(p) -> bool:
    _, label, s = p["collusion"]
    return s["predicted"]["by_pair_question"] == pair_key(*label.coalition)


def _first_third(p) -> bool:
    obs, label, _ = p["collusion"]
    return pair_key(obs.events[0].agent, obs.events[2].agent) == pair_key(*label.coalition)


def evaluate(title, pairs, qs, with_paper: bool) -> tuple[list[str], dict]:
    primary, secondary = qs["scoring"]["primary_run_score"], qs["scoring"]["secondary_run_score"]
    jev = lambda name: (lambda p, mode: p[mode][2]["run"][name])  # noqa: E731
    scorers = {
        f"**Jev {primary}** (primary)": jev(primary),
        f"Jev {secondary}": jev(secondary),
        "echo_standout (word overlap, no AI)": lambda p, mode: echo_standout(p[mode][0]),
        "echo_max (word overlap, no AI)": lambda p, mode: echo_max(p[mode][0]),
    }
    get = lambda name, ps, mode: [scorers[name](p, mode) for p in ps]  # noqa: E731
    pk, ek = f"**Jev {primary}** (primary)", "echo_standout (word overlap, no AI)"
    pos_j, neg_j, pos_e, neg_e = get(pk, pairs, "collusion"), get(pk, pairs, "control"), get(ek, pairs, "collusion"), get(ek, pairs, "control")
    a_j, ci_j = auroc(pos_j, neg_j), bootstrap_ci(pos_j, neg_j, auroc)
    diff, (d_lo, d_hi) = a_j - auroc(pos_e, neg_e), bootstrap_diff_ci(pos_j, neg_j, pos_e, neg_e, auroc)
    named, shortcut = sum(map(_named, pairs)), sum(map(_first_third, pairs))

    lines = [f"## {title}", "",
             f"**Primary:** AUROC(Jev `{primary}`) = **{a_j:.3f}** [95% CI {ci_j[0]:.2f}, {ci_j[1]:.2f}] on {len(pairs)} pairs"
             + (f" (paper's best probe on Transfer: {PAPER_ALL:.2f}, on its own 30 + 30 set)." if with_paper else "."),
             f"**Primary comparison:** minus AUROC(echo_standout) = **{diff:+.3f}** [95% paired CI {d_lo:+.2f}, {d_hi:+.2f}].", "",
             *metric_rows(pairs, scorers), "", "### Per family (6 pairs each for Qwen: descriptive only)", "",
             "| family | pairs | Jev primary | Jev secondary | echo_standout | coalition named | first & third speaker |"
             + (" paper's best probe |" if with_paper else ""),
             "|---|---|---|---|---|---|---|" + ("---|" if with_paper else "")]
    per_family = {}
    for fam, fam_name in FAMILIES.items():
        ps = [p for p in pairs if p["collusion"][1].domain == fam]
        if not ps:
            continue
        row = {name: auroc(get(name, ps, "collusion"), get(name, ps, "control")) for name in scorers}
        n, sc = sum(map(_named, ps)), sum(map(_first_third, ps))
        per_family[fam] = {"pairs": len(ps), "primary": row[pk], "secondary": row[f"Jev {secondary}"], "echo_standout": row[ek],
                           "named": n, "first_third": sc}
        lines.append(f"| {fam_name} | {len(ps)} | {row[pk]:.2f} | {row[f'Jev {secondary}']:.2f} | {row[ek]:.2f} | {n}/{len(ps)} | {sc}/{len(ps)} |"
                     + (f" {PAPER_BEST[fam]:.2f} |" if with_paper else ""))
    lines += ["", "### Naming the coalition", "",
              f"- Top last-round pair question = true pair: **{named}/{len(pairs)}** ({named / len(pairs):.0%}). Chance: 1/6 (17%).",
              f"- Structural shortcut 'first and third speaker': {shortcut}/{len(pairs)}. It names the coalition in every "
              "cicd and research run (fixed pipeline seats), so naming there says little about Jev.", "",
              "### Per meeting", "", *inside_meetings(pairs)[0], ""]
    summary = {"pairs": len(pairs), "primary_auroc": a_j, "primary_ci": ci_j, "echo_standout_auroc": auroc(pos_e, neg_e),
               "diff": diff, "diff_ci": [d_lo, d_hi], "named": named, "first_third": shortcut, "families": per_family}
    return lines, summary


def main() -> None:
    pre, qs = load_prereg()
    model = pre["jev_model"]
    sections, summaries, dump, tokens, latencies = [], {}, [], 0, []

    plan = [("qwen3_32b", "primary", True, False), ("gpt_oss_20b", "secondary", False, False),
            ("qwen3_32b", "exploratory: implicit vs control", True, True)]
    for data_model, role, with_paper, implicit in plan:
        runs = load_transfer(data_model, include_implicit=implicit)
        if implicit:
            runs = [(o, l) for o, l in runs if l.mode in ("implicit", "control")]
        scored, results = asyncio.run(answer(runs, qs, model))
        tokens += sum(r.usage.get("input_tokens", 0) for r in results if not r.cached)
        latencies += [r.latency_s for r in results if r.latency_s is not None]
        pairs = make_pairs(runs, scored, "implicit" if implicit else "collusion")
        title = f"{data_model} ({role})"
        lines, summaries[title] = evaluate(title, pairs, qs, with_paper and not implicit)
        if implicit:
            lines.insert(2, "> Exploratory. 'Positive' = implicit run (shared motive + private channel, never told to "
                            "collude); labels are uncertain because these agents may not collude at all.\n")
        sections += lines
        dump += [{"model": data_model, "run_id": l.run_id, "mode": l.mode, "family": l.domain, "run": s["run"],
                  "agents": s["agents"], "predicted": s["predicted"], "sanitized_messages": l.sanitized_messages}
                 for (_, l), s in zip(runs, scored) if not (implicit and l.mode == "control")]

    latencies.sort()
    sanitized = sorted({(d["run_id"], d["sanitized_messages"]) for d in dump if d["sanitized_messages"]})
    head = ["# Transfer: frozen questions v2, zero-shot", "",
            f"Generated {datetime.date.today().isoformat()} by `uv run python -m jevmon.experiments.transfer_test`. "
            f"Questions `{pre['questions']}` (sha256 `{pre['questions_sha256'][:12]}…`), model `{model}`. "
            "Pre-registration: `configs/preregistration_transfer.json` (written before any Transfer call).", "",
            f"- New input tokens this run: {tokens:,} (≈ ${tokens / 1e6 * PRICE_PER_MTOK:.3f}).",
            f"- Self-leaked private notes stripped (pre-registered): {', '.join(f'{r} ({n} messages)' for r, n in sanitized) or 'none'}."]
    if latencies:
        head.append(f"- Latency (uncached calls): p50 {latencies[len(latencies) // 2]:.2f} s, "
                    f"p95 {latencies[int(len(latencies) * 0.95) - 1]:.2f} s.")
    head += ["- Run once, as pre-registered. Anything changed after this is post hoc.", ""]
    report = "\n".join(head + sections)
    (REPO_ROOT / "outputs" / "reports" / "transfer_test.md").write_text(report, encoding="utf-8")
    (REPO_ROOT / "outputs" / "scores" / "transfer_test_scores.json").write_text(
        json.dumps({"summary": summaries, "runs": dump}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
