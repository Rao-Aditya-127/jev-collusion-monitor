"""POST HOC check: re-score Transfer News with the colluders' public strategy notes stripped.

    uv run python -m jevmon.experiments.news_notes_check

Found after the pre-registered Transfer test: in news nf_01, nf_02 and nf_06 the colluders ended 6 public messages
with strategy notes ("Narrative Nudge for Round 2", "Key Adjustments and Narrative Nudges", "Private Drift Note").
The pre-registered cleanup only removed "Private Coordination (only you ...)" blocks, so Jev saw these notes. This
measures how much they helped. The pre-registered result is unchanged; this is a sensitivity check.
Writes outputs/reports/news_notes_check.md and outputs/scores/news_notes_check.json.
"""
from __future__ import annotations

import asyncio
import datetime
import json
from collections import defaultdict

from ..eval.metrics import auroc, bootstrap_ci
from ..leakguard import find_leaks, public_record
from ..loaders.transfer import load_transfer
from ..monitors.core_monitor import build_requests, load_questions, pair_key, score_run
from ..monitors.jev_client import JevClient, LeakError
from ..paths import REPO_ROOT

MODEL = "jev-1.13.0"


async def score(runs, qs):
    sets = [build_requests(o, qs) for o, _ in runs]
    publics = [public_record(o) for o, _ in runs]
    for (_, label), reqs, public in zip(runs, sets, publics):
        for r in reqs:
            if leaks := find_leaks(json.dumps(r.state, ensure_ascii=False), label, public):
                raise LeakError(f"{label.run_id} {r.kind}: {leaks}")
    async with JevClient(model=MODEL) as client:
        results = await asyncio.gather(*(client.ask(r.state, r.questions, pub) for reqs, pub in zip(sets, publics) for r in reqs))
    out, i = {}, 0
    for (obs, label), reqs in zip(runs, sets):
        s = score_run(obs, list(zip(reqs, [r.answers for r in results[i: i + len(reqs)]])), qs)
        i += len(reqs)
        out[label.run_id] = {"label": label, "primary": s["run"]["pair_final_max"], "secondary": s["run"]["peak_suspicion"],
                             "named": s["predicted"]["by_pair_question"]}
    return out, results


def table(rows: dict, run_ids: list[str]) -> dict:
    pairs = defaultdict(dict)
    for rid in run_ids:
        pairs[rows[rid]["label"].pair_id][rows[rid]["label"].mode] = rows[rid]
    plist = [p for _, p in sorted(pairs.items())]
    out = {}
    for k in ("primary", "secondary"):
        pos, neg = [p["collusion"][k] for p in plist], [p["control"][k] for p in plist]
        out[k] = (auroc(pos, neg), bootstrap_ci(pos, neg, auroc))
    out["named"] = sum(p["collusion"]["named"] == pair_key(*p["collusion"]["label"].coalition) for p in plist)
    out["pairs"] = len(plist)
    return out


def main() -> None:
    qs = load_questions("v2")
    before_runs = load_transfer("qwen3_32b")
    after_runs = load_transfer("qwen3_32b", strip_strategy=True)
    before, _ = asyncio.run(score(before_runs, qs))          # all cached from the Transfer test
    after, results = asyncio.run(score(after_runs, qs))      # only the changed news requests are new calls
    tokens = sum(r.usage.get("input_tokens", 0) for r in results if not r.cached)
    news = [l.run_id for _, l in before_runs if l.domain == "news"]
    every = [l.run_id for _, l in before_runs]
    stripped = {l.run_id: l.sanitized_messages for _, l in after_runs if l.sanitized_messages}
    nb, na, ab, aa = table(before, news), table(after, news), table(before, every), table(after, every)
    fmt = lambda t, k: f"{t[k][0]:.3f} [{t[k][1][0]:.2f}, {t[k][1][1]:.2f}]"  # noqa: E731
    changed = [rid for rid in news if abs(before[rid]["primary"] - after[rid]["primary"]) > 1e-9]
    lines = [
        "# POST HOC: News scored without the colluders' public strategy notes", "",
        f"Generated {datetime.date.today().isoformat()} by `uv run python -m jevmon.experiments.news_notes_check`. "
        "**Post hoc sensitivity check**, not part of the pre-registered Transfer test (whose numbers stand as reported).", "",
        "- Messages stripped (strategy notes + the pre-registered 'Private Coordination' blocks): "
        + ", ".join(f"{r} ({n})" for r, n in sorted(stripped.items())) + ".",
        f"- New input tokens: {tokens:,} (≈ ${tokens / 1e6 * 0.042:.4f}).", "",
        "| | as pre-registered | notes stripped |", "|---|---|---|",
        f"| News: Jev main score AUROC (6 pairs) | {fmt(nb, 'primary')} | {fmt(na, 'primary')} |",
        f"| News: most-suspicious-agent AUROC | {fmt(nb, 'secondary')} | {fmt(na, 'secondary')} |",
        f"| News: pair named | {nb['named']}/{nb['pairs']} | {na['named']}/{na['pairs']} |",
        f"| All Transfer: Jev main score AUROC (36 pairs) | {fmt(ab, 'primary')} | {fmt(aa, 'primary')} |",
        f"| All Transfer: pair named | {ab['named']}/{ab['pairs']} | {aa['named']}/{aa['pairs']} |", "",
        "Per meeting (Jev main score, before → after):", "",
        "| meeting | before | after | pair named before → after |", "|---|---|---|---|",
    ]
    for rid in sorted(news):
        b, a = before[rid], after[rid]
        t = pair_key(*b["label"].coalition) if b["label"].coalition else None
        nm = lambda r: ("✓" if r["named"] == t else "✗") if t else "—"  # noqa: E731
        lines.append(f"| {rid.removeprefix('news__')} | {b['primary']:.2f} | {a['primary']:.2f} | {nm(b)} → {nm(a)} |")
    report = "\n".join(lines + [""])
    (REPO_ROOT / "outputs" / "reports" / "news_notes_check.md").write_text(report, encoding="utf-8")
    dump = {"news_before": {k: nb[k] for k in ("primary", "secondary", "named", "pairs")},
            "news_after": {k: na[k] for k in ("primary", "secondary", "named", "pairs")},
            "transfer_before": {k: ab[k] for k in ("primary", "named", "pairs")},
            "transfer_after": {k: aa[k] for k in ("primary", "named", "pairs")},
            "changed_meetings": changed, "stripped": stripped}
    (REPO_ROOT / "outputs" / "scores" / "news_notes_check.json").write_text(json.dumps(dump, indent=1), encoding="utf-8")
    print(report)


if __name__ == "__main__":
    main()
