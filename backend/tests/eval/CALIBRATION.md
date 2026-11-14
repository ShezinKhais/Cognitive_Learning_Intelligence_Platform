# Calibration and consistency

Read from the classifier results in this folder; unreadable replies are left out. ECE (expected calibration error, 10 bins) and the Brier score are 0 when confidence is perfectly honest; AUROC is the chance a right label has higher confidence than a wrong one (1 perfect, 0.5 a coin toss).

## Calibration

| Run | Labels | Mean confidence | Accuracy | ECE | Brier | AUROC |
|---|---|---|---|---|---|---|
| qwen2.5:3b v3 run 2 | 33 | 0.70 | 82% | 0.17 | 0.16 | 0.74 |
| qwen2.5:7b v3 run 1 | 34 | 0.73 | 79% | 0.13 | 0.18 | 0.62 |
| qwen2.5:7b v3 run 2 | 37 | 0.71 | 84% | 0.20 | 0.17 | 0.60 |
| qwen2.5:3b v4 | 40 | 0.73 | 78% | 0.14 | 0.18 | 0.61 |
| qwen2.5:3b v5 | 40 | 0.73 | 80% | 0.24 | 0.19 | 0.62 |

How often labels were right at each confidence level:

| Run | Below 0.6 | 0.6 to 0.85 | 0.85 and up |
|---|---|---|---|
| qwen2.5:3b v3 run 2 | 8 of 12 right | 8 of 10 right | 11 of 11 right |
| qwen2.5:7b v3 run 1 | 7 of 9 right | 9 of 13 right | 11 of 12 right |
| qwen2.5:7b v3 run 2 | 9 of 11 right | 10 of 13 right | 12 of 13 right |
| qwen2.5:3b v4 | 9 of 12 right | 8 of 12 right | 14 of 16 right |
| qwen2.5:3b v5 | 9 of 11 right | 8 of 13 right | 15 of 16 right |

What each review threshold would do: labels below it are shown as "Uncertain, ask your lecturer" (hidden), the rest with their label (shown); wrong counts in brackets:

| Run | Below 0.35: hidden (wrong) / shown (wrong) | Below 0.60: hidden (wrong) / shown (wrong) | Below 0.85: hidden (wrong) / shown (wrong) |
|---|---|---|---|
| qwen2.5:3b v3 run 2 | 0 (0) / 33 (6) | 12 (4) / 21 (2) | 22 (6) / 11 (0) |
| qwen2.5:7b v3 run 1 | 0 (0) / 34 (7) | 9 (2) / 25 (5) | 22 (6) / 12 (1) |
| qwen2.5:7b v3 run 2 | 0 (0) / 37 (6) | 11 (2) / 26 (4) | 24 (5) / 13 (1) |
| qwen2.5:3b v4 | 0 (0) / 40 (9) | 12 (3) / 28 (6) | 24 (7) / 16 (2) |
| qwen2.5:3b v5 | 0 (0) / 40 (8) | 11 (2) / 29 (6) | 24 (7) / 16 (1) |

## Consistency

| Runs compared | Answers both read | Same label | Cohen's kappa |
|---|---|---|---|
| qwen2.5:7b v3 run 1 vs qwen2.5:7b v3 run 2 | 33 | 29 (88%) | 0.82 |
