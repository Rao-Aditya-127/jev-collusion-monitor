import pytest
from sklearn.metrics import roc_auc_score

from jevmon.eval.metrics import auroc, bootstrap_ci, bootstrap_diff_ci, pair_win_rate, tpr_at_fpr


def test_auroc_matches_sklearn_with_ties():
    pos, neg = [3, 2, 2, 0], [2, 1, 0, 0]
    expected = roc_auc_score([1] * 4 + [0] * 4, pos + neg)
    assert auroc(pos, neg) == pytest.approx(expected)


def test_pair_win_rate_uses_pairing():
    # Every collusion run beats its own control, though not every control overall.
    assert pair_win_rate([1, 5], [0, 4]) == 1.0
    assert auroc([1, 5], [0, 4]) == 0.75
    assert pair_win_rate([1, 1], [1, 0]) == 0.75


def test_tpr_at_fpr():
    pos, neg = [5, 4, 3, 1], [3, 2, 1, 0]
    assert tpr_at_fpr(pos, neg, 0.0) == 0.5  # threshold 3: only 5 and 4 exceed every control
    assert tpr_at_fpr(pos, neg, 0.25) == 0.75  # threshold 2: one control (3) exceeds it
    assert tpr_at_fpr(pos, neg, 1.0) == 1.0


def test_bootstrap_ci_brackets_point_estimate():
    pos, neg = [3, 2, 2, 5, 1, 4], [1, 2, 0, 3, 1, 1]
    lo, hi = bootstrap_ci(pos, neg, auroc, n_boot=500)
    assert lo <= auroc(pos, neg) <= hi
    assert bootstrap_ci([1, 1], [0, 0], auroc, n_boot=50) == (1.0, 1.0)


def test_bootstrap_diff_ci():
    pos, neg = [3, 2, 2, 5, 1, 4], [1, 2, 0, 3, 1, 1]
    assert bootstrap_diff_ci(pos, neg, pos, neg, auroc, n_boot=200) == (0.0, 0.0)  # identical scorers
    lo, hi = bootstrap_diff_ci([1] * 6, [0] * 6, pos, neg, auroc, n_boot=500)
    assert 0 <= lo <= 1 - auroc(pos, neg) <= hi
