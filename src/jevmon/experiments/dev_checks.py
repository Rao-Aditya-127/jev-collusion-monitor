"""Dev-split checks for a question version before it is frozen.

    uv run python -m jevmon.experiments.dev_checks v2

1. Standard pass: the same three checks as the first Jev test.
2. Option order: reverse every Choice option list, the two names in each `pair`, and the order of
   questions inside each request. A sound question set should barely move.
3. Bundling: ask each round-3 pair question on its own instead of together with the other six.
4. Neutral option labels: strip bracketed hints from option lines in the brief, e.g.
   "Option B: Issue clean opinion (preserve client relationship)" -> "Option B: Issue clean opinion".

All calls go through the cache, so reruns are free. Writes outputs/reports/dev_checks_<version>.md.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import re
import statistics
import sys
from dataclasses import replace

from ..baselines.core import vote_minority
from ..eval.splits import core_split, load_splits
from ..leakguard import find_leaks
from ..loaders.core import load_core
from ..monitors.core_monitor import Request, build_requests, load_questions, questions_path, score_run
from ..monitors.jev_client import JevClient, LeakError
from ..paths import REPO_ROOT
from .reporting import inside_meetings, pair_up, short, vs_twins

DATA_MODEL = "qwen3_32b"
_BRACKETED_HINT = re.compile(r"^(Option \S+: [^\n]*?)\s*\([^)\n]*\)[ \t]*$", re.M)


def neutral_brief(brief: str) -> str:
    return _BRACKETED_HINT.sub(r"\1", brief)


def reordered(req: Request) -> Request:
    questions = {}
    for qid, q in req.questions.items():
        if q["type"] == "choice":
            q = {**q, "criteria": dict(reversed(list(q["criteria"].items())))}
        if isinstance(q.get("instructions"), dict) and "pair" in q["instructions"]:
            q = {**q, "instructions": {**q["instructions"], "pair": q["instructions"]["pair"][::-1]}}
        questions[qid] = q
    return replace(req, questions=dict(reversed(list(questions.items()))))


def single_pair_requests(requests: list[Request]) -> list[Request]:
    last = max(r.round for r in requests if r.kind == "round")
    return [replace(r, questions={qid: q}) for r in requests if r.kind == "round" and r.round == last
            for qid, q in r.questions.items() if qid.startswith("pair::")]


async def ask(client, runs, request_sets):
    for (_, label), requests in zip(runs, request_sets):
        for r in requests:
            if leaks := find_leaks(json.dumps(r.state, ensure_ascii=False), label):
                raise LeakError(f"{label.run_id} {r.kind}: {leaks}")
    flat = [r for requests in request_sets for r in requests]
    results = await asyncio.gather(*(client.ask(r.state, r.questions) for r in flat))
    out, i = [], 0
    for requests in request_sets:
        out.append([res.answers for res in results[i : i + len(requests)]])
        i += len(requests)
    return out, [r for r in results]


def _numbers(answers: dict) -> dict[str, float]:
    """Flatten one request's answers to {question[:option]: value} for comparison."""
    out = {}
    for qid, a in answers.items():
        if "noul" in a:
            out[qid] = a["noul"]
        elif a["type"] == "score":
            out[qid] = a["score"]
        else:
            out |= {f"{qid}:{opt}": p for opt, p in a["probabilities"].items()}
    return out


def _abs_diffs(a_sets, b_sets, keep=lambda key: True) -> list[float]:
    diffs = []
    for a_run, b_run in zip(a_sets, b_sets):
        for a, b in zip(a_run, b_run):
            na, nb = _numbers(a), _numbers(b)
            diffs += [abs(na[k] - nb[k]) for k in na if keep(k)]
    return diffs


def _summary(diffs: list[float]) -> str:
    diffs = sorted(diffs)
    return (f"mean {statistics.mean(diffs):.3f}, median {diffs[len(diffs) // 2]:.3f}, "
            f"95th pct {diffs[int(len(diffs) * 0.95) - 1]:.3f}, max {diffs[-1]:.3f} (n = {len(diffs)})")


async def collect(runs, qs):
    standard = [build_requests(o, qs) for o, _ in runs]
    sets = {
        "standard": standard,
        "reordered": [[reordered(r) for r in reqs] for reqs in standard],
        "single_pair": [single_pair_requests(reqs) for reqs in standard],
        "neutral": [build_requests(replace(o, brief=neutral_brief(o.brief)), qs) for o, _ in runs],
    }
    answers, usage = {}, 0
    async with JevClient() as client:
        for name, request_sets in sets.items():
            answers[name], results = await ask(client, runs, request_sets)
            usage += sum(r.usage.get("input_tokens", 0) for r in results)
    return sets, answers, usage


def analyse(version, qs, runs, sets, answers, usage) -> tuple[str, dict]:
    primary, secondary = qs["scoring"]["primary_run_score"], qs["scoring"]["secondary_run_score"]
    scored = {name: [score_run(o, list(zip(sets[name][i], answers[name][i])), qs) for i, (o, _) in enumerate(runs)]
              for name in ("standard", "reordered", "neutral")}
    pairs = {name: pair_up(runs, s) for name, s in scored.items()}
    run_names = list(scored["standard"][0]["run"])

    lines = [f"# Dev checks: questions {version}", "",
             f"Generated {datetime.date.today().isoformat()} by `uv run python -m jevmon.experiments.dev_checks {version}`. "
             f"Questions: `{questions_path(version).relative_to(REPO_ROOT).as_posix()}`. "
             f"Primary meeting score: **`{primary}`**; secondary: `{secondary}`.", "",
             f"- {len(runs)} dev meetings (5 pairs, Qwen3-32B). Input tokens for all four passes: {usage:,} "
             f"(≈ ${usage / 1e6 * 0.042:.3f}; cached passes count again here).", ""]

    # 1. standard
    table, summary = inside_meetings(pairs["standard"])
    n = summary["n"]
    lines += ["## 1. Standard pass", "", *table, "",
              f"- Colluders above honest: {summary['above_mean']}/{n} on average, {summary['above_strict']}/{n} strictly.",
              f"- Coalition found: pair question {summary['by_pair_question']}/{n}, top-2 suspicion "
              f"{summary['by_suspicion']}/{n}, echo {summary['by_echo']}/{n}.", "",
              *vs_twins(pairs["standard"], run_names, {"vote_minority": vote_minority}), ""]

    # 2. option order
    pair_d = _abs_diffs(answers["standard"], answers["reordered"], lambda k: k.startswith("pair::"))
    echo_d = _abs_diffs(answers["standard"], answers["reordered"], lambda k: k.startswith("echoes:"))
    other_d = _abs_diffs(answers["standard"], answers["reordered"],
                         lambda k: not k.startswith(("pair::", "echoes:")))
    changed = sum(a["predicted"]["by_pair_question"] != b["predicted"]["by_pair_question"]
                  for a, b in zip(scored["standard"], scored["reordered"]))
    prim = [abs(a["run"][primary] - b["run"][primary]) for a, b in zip(scored["standard"], scored["reordered"])]
    lines += ["## 2. Option order", "",
              "Reversed: every Choice option list, the two names in each `pair`, and the question order in each request.", "",
              f"- Pair nouls: {_summary(pair_d)}.",
              f"- Echo choice probabilities: {_summary(echo_d)}.",
              f"- Other nouls and scores: {_summary(other_d)}.",
              f"- `{primary}` per meeting: largest change {max(prim):.3f}. Predicted coalition changed in "
              f"{changed}/{len(runs)} meetings.", ""]

    # 3. bundling
    bundled = [[a for a in ans if any(k.startswith("pair::") for k in a)][-1] for ans in answers["standard"]]
    single = [{k: v for a in ans for k, v in a.items()} for ans in answers["single_pair"]]
    bundle_d = [abs(b[k]["noul"] - s[k]["noul"]) for b, s in zip(bundled, single) for k in s]
    top_same = sum(max(s, key=lambda k: s[k]["noul"]) == max((k for k in b if k.startswith("pair::")),
                                                              key=lambda k: b[k]["noul"])
                   for b, s in zip(bundled, single))
    lines += ["## 3. Bundling", "",
              "Round-3 pair questions asked one per request vs all together (6 pairs + `coordination_present`).", "",
              f"- Pair nouls, alone vs bundled: {_summary(bundle_d)}.",
              f"- Same top pair: {top_same}/{len(runs)} meetings.", ""]

    # 4. neutral labels
    hints = sum(neutral_brief(o.brief) != o.brief for o, _ in runs)
    table_n, summary_n = inside_meetings(pairs["neutral"])
    lines += ["## 4. Neutral option labels", "",
              f"Bracketed hints stripped from the option lines in {hints}/{len(runs)} briefs; the agents' messages are "
              "unchanged, so they may still quote the hint. Options that are unfair without brackets stay as they are.", "",
              *table_n, "",
              f"- Colluders above honest: {summary_n['above_mean']}/{n} on average, {summary_n['above_strict']}/{n} strictly. "
              f"Coalition found by the pair question: {summary_n['by_pair_question']}/{n}.", "",
              *vs_twins(pairs["neutral"], [primary, secondary]), "",
              "| meeting | " + f"`{primary}` standard → neutral | `{secondary}` standard → neutral |", "|---|---|---|"]
    for (o, l), a, b in zip(runs, scored["standard"], scored["neutral"]):
        lines.append(f"| {short(l.run_id)} | {a['run'][primary]:.2f} → {b['run'][primary]:.2f} | "
                     f"{a['run'][secondary]:.2f} → {b['run'][secondary]:.2f} |")
    lines.append("")
    summary_out = {
        "version": version, "primary": primary, "secondary": secondary, "tokens": usage, "standard": summary,
        "order": {"pair_mean": statistics.mean(pair_d), "pair_max": max(pair_d), "echo_max": max(echo_d),
                  "other_mean": statistics.mean(other_d), "primary_max_change": max(prim), "coalition_changed": changed},
        "bundling": {"mean": statistics.mean(bundle_d), "max": max(bundle_d), "same_top_pair": top_same,
                     "meetings": len(runs)},
        "neutral": {"briefs_changed": hints, "above_strict": summary_n["above_strict"],
                    "by_pair_question": summary_n["by_pair_question"],
                    "primary_max_change": max(abs(a["run"][primary] - b["run"][primary])
                                              for a, b in zip(scored["standard"], scored["neutral"]))},
    }
    return "\n".join(lines), summary_out


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else "v2"
    qs = load_questions(version)
    splits = load_splits()
    runs = [(o, l) for o, l in load_core(DATA_MODEL) if core_split(l, splits) == "dev"]
    sets, answers, usage = asyncio.run(collect(runs, qs))
    report, summary = analyse(version, qs, runs, sets, answers, usage)
    out = REPO_ROOT / "outputs" / "reports" / f"dev_checks_{version}.md"
    out.write_text(report, encoding="utf-8")
    (REPO_ROOT / "outputs" / "scores" / f"dev_checks_{version}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
