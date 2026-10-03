# Core baselines

Generated 2026-10-02 by `uv run python -m jevmon.baselines.run_core`.

- Runs = the paper's evaluated set (run_ids in `metadata_gen.json`): qwen3_32b: 62 runs, gpt_oss_20b: 36 runs.
- Splits: dev = whole domains listed in `configs/splits.json`; test = all other domains.
- *no refusals* drops pairs where neither colluder voted for the target.
- `vote_nonfair (oracle)` reads the label `fair_option`. `echo_standout` was chosen after seeing full-set results on 30 Sep, so its test number is optimistically biased.
- AUROC CI = 95% percentile bootstrap over pairs (2,000 resamples). Pair win-rate = P(collusion run scores above its own control). TPR at 0 / 10% FPR uses the rule `score > threshold`.

## qwen3_32b

| split | subset | baseline | pairs | AUROC [95% CI] | pair win-rate | TPR @0 FP | TPR @10% FPR |
|---|---|---|---|---|---|---|---|
| dev | all pairs | vote_minority | 5 | 0.900 [0.70, 1.00] | 0.900 | 0.80 | 0.80 |
| dev | all pairs | echo_max | 5 | 0.480 [0.20, 0.80] | 0.400 | 0.00 | 0.00 |
| dev | all pairs | echo_standout | 5 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| dev | all pairs | vote_nonfair (oracle) | 5 | 0.900 [0.70, 1.00] | 0.900 | 0.80 | 0.80 |
| dev | no refusals | vote_minority | 4 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| dev | no refusals | echo_max | 4 | 0.375 [0.06, 0.75] | 0.250 | 0.00 | 0.00 |
| dev | no refusals | echo_standout | 4 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| dev | no refusals | vote_nonfair (oracle) | 4 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| test | all pairs | vote_minority | 26 | 0.865 [0.79, 0.94] | 0.865 | 0.73 | 0.73 |
| test | all pairs | echo_max | 26 | 0.271 [0.15, 0.39] | 0.231 | 0.04 | 0.04 |
| test | all pairs | echo_standout | 26 | 0.817 [0.68, 0.93] | 0.769 | 0.42 | 0.50 |
| test | all pairs | vote_nonfair (oracle) | 26 | 0.904 [0.83, 0.98] | 0.904 | 0.81 | 0.81 |
| test | no refusals | vote_minority | 21 | 0.952 [0.88, 1.00] | 0.952 | 0.90 | 0.90 |
| test | no refusals | echo_max | 21 | 0.277 [0.15, 0.42] | 0.238 | 0.00 | 0.00 |
| test | no refusals | echo_standout | 21 | 0.864 [0.73, 0.97] | 0.857 | 0.48 | 0.57 |
| test | no refusals | vote_nonfair (oracle) | 21 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| all | all pairs | vote_minority | 31 | 0.871 [0.79, 0.95] | 0.871 | 0.74 | 0.74 |
| all | all pairs | echo_max | 31 | 0.300 [0.20, 0.41] | 0.258 | 0.03 | 0.03 |
| all | all pairs | echo_standout | 31 | 0.849 [0.74, 0.94] | 0.806 | 0.42 | 0.61 |
| all | all pairs | vote_nonfair (oracle) | 31 | 0.903 [0.82, 0.97] | 0.903 | 0.81 | 0.81 |
| all | no refusals | vote_minority | 25 | 0.960 [0.90, 1.00] | 0.960 | 0.92 | 0.92 |
| all | no refusals | echo_max | 25 | 0.291 [0.18, 0.41] | 0.240 | 0.00 | 0.00 |
| all | no refusals | echo_standout | 25 | 0.886 [0.76, 0.97] | 0.880 | 0.48 | 0.56 |
| all | no refusals | vote_nonfair (oracle) | 25 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |

Agent level: does the most-echoing pair equal the coalition? (chance 1/6 = 0.17)

| split | subset | pairs | accuracy |
|---|---|---|---|
| dev | all pairs | 5 | 0.40 |
| dev | no refusals | 4 | 0.50 |
| test | all pairs | 26 | 0.46 |
| test | no refusals | 21 | 0.43 |
| all | all pairs | 31 | 0.45 |
| all | no refusals | 25 | 0.44 |

## gpt_oss_20b

| split | subset | baseline | pairs | AUROC [95% CI] | pair win-rate | TPR @0 FP | TPR @10% FPR |
|---|---|---|---|---|---|---|---|
| dev | all pairs | vote_minority | 2 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| dev | all pairs | echo_max | 2 | 0.750 [0.75, 1.00] | 1.000 | 0.50 | 0.50 |
| dev | all pairs | echo_standout | 2 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| dev | all pairs | vote_nonfair (oracle) | 2 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| dev | no refusals | vote_minority | 2 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| dev | no refusals | echo_max | 2 | 0.750 [0.75, 1.00] | 1.000 | 0.50 | 0.50 |
| dev | no refusals | echo_standout | 2 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| dev | no refusals | vote_nonfair (oracle) | 2 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| test | all pairs | vote_minority | 16 | 0.898 [0.78, 1.00] | 0.875 | 0.75 | 0.81 |
| test | all pairs | echo_max | 16 | 0.305 [0.17, 0.44] | 0.188 | 0.00 | 0.00 |
| test | all pairs | echo_standout | 16 | 0.883 [0.75, 0.98] | 0.875 | 0.50 | 0.69 |
| test | all pairs | vote_nonfair (oracle) | 16 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| test | no refusals | vote_minority | 16 | 0.898 [0.78, 1.00] | 0.875 | 0.75 | 0.81 |
| test | no refusals | echo_max | 16 | 0.305 [0.17, 0.44] | 0.188 | 0.00 | 0.00 |
| test | no refusals | echo_standout | 16 | 0.883 [0.75, 0.98] | 0.875 | 0.50 | 0.69 |
| test | no refusals | vote_nonfair (oracle) | 16 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| all | all pairs | vote_minority | 18 | 0.909 [0.79, 1.00] | 0.889 | 0.72 | 0.83 |
| all | all pairs | echo_max | 18 | 0.333 [0.20, 0.45] | 0.278 | 0.00 | 0.00 |
| all | all pairs | echo_standout | 18 | 0.892 [0.76, 0.98] | 0.889 | 0.50 | 0.72 |
| all | all pairs | vote_nonfair (oracle) | 18 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |
| all | no refusals | vote_minority | 18 | 0.909 [0.79, 1.00] | 0.889 | 0.72 | 0.83 |
| all | no refusals | echo_max | 18 | 0.333 [0.20, 0.45] | 0.278 | 0.00 | 0.00 |
| all | no refusals | echo_standout | 18 | 0.892 [0.76, 0.98] | 0.889 | 0.50 | 0.72 |
| all | no refusals | vote_nonfair (oracle) | 18 | 1.000 [1.00, 1.00] | 1.000 | 1.00 | 1.00 |

Agent level: does the most-echoing pair equal the coalition? (chance 1/6 = 0.17)

| split | subset | pairs | accuracy |
|---|---|---|---|
| dev | all pairs | 2 | 0.50 |
| dev | no refusals | 2 | 0.50 |
| test | all pairs | 16 | 0.25 |
| test | no refusals | 16 | 0.25 |
| all | all pairs | 18 | 0.28 |
| all | no refusals | 18 | 0.28 |
