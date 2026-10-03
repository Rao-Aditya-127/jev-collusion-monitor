"""Run-level detection metrics. Collusion and control runs come in matched pairs, so the
bootstrap resamples whole pairs and `pair_win_rate` compares each collusion run with its own control."""
from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np


def auroc(pos: Sequence[float], neg: Sequence[float]) -> float:
    """Mann-Whitney AUROC, ties counted as 0.5."""
    p = np.asarray(pos, float)[:, None]
    n = np.asarray(neg, float)[None, :]
    return float(((p > n) + 0.5 * (p == n)).mean())


def pair_win_rate(pos: Sequence[float], neg: Sequence[float]) -> float:
    """P(collusion score > its paired control score), ties 0.5. `pos[i]` and `neg[i]` must be a pair."""
    p = np.asarray(pos, float)
    n = np.asarray(neg, float)
    return float(((p > n) + 0.5 * (p == n)).mean())


def tpr_at_fpr(pos: Sequence[float], neg: Sequence[float], max_fpr: float) -> float:
    """TPR of the rule `score > t` for the lowest threshold t whose FPR is at most `max_fpr`."""
    p = np.asarray(pos, float)
    n = np.asarray(neg, float)
    for t in np.unique(np.concatenate([p, n])):  # ascending, so the first hit has the highest TPR
        if (n > t).mean() <= max_fpr:
            return float((p > t).mean())
    return 0.0


def bootstrap_diff_ci(
    pos_a: Sequence[float],
    neg_a: Sequence[float],
    pos_b: Sequence[float],
    neg_b: Sequence[float],
    stat: Callable[[np.ndarray, np.ndarray], float],
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile CI for stat(a) - stat(b) when both scorers rate the same pairs (paired bootstrap)."""
    arrays = [np.asarray(x, float) for x in (pos_a, neg_a, pos_b, neg_b)]
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(arrays[0]), size=(n_boot, len(arrays[0])))
    values = [stat(arrays[0][i], arrays[1][i]) - stat(arrays[2][i], arrays[3][i]) for i in draws]
    lo, hi = np.quantile(values, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)


def bootstrap_ci(
    pos: Sequence[float],
    neg: Sequence[float],
    stat: Callable[[np.ndarray, np.ndarray], float],
    n_boot: int = 2000,
    seed: int = 0,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Percentile CI for `stat`, resampling pairs (pos[i], neg[i]) with replacement."""
    p = np.asarray(pos, float)
    n = np.asarray(neg, float)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(p), size=(n_boot, len(p)))
    values = [stat(p[idx], n[idx]) for idx in draws]
    lo, hi = np.quantile(values, [alpha / 2, 1 - alpha / 2])
    return float(lo), float(hi)
