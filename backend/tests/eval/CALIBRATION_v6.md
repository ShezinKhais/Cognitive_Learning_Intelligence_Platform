# Calibration and consistency

Read from the classifier results in this folder; unreadable replies are left out. ECE (expected calibration error, 10 bins) and the Brier score are 0 when confidence is perfectly honest; AUROC is the chance a right label has higher confidence than a wrong one (1 perfect, 0.5 a coin toss).

## Calibration

| Run | Labels | Mean confidence | Accuracy | ECE | Brier | AUROC |
|---|---|---|---|---|---|---|
| qwen2.5:3b v6 | 40 | 0.71 | 80% | 0.25 | 0.20 | 0.59 |

How often labels were right at each confidence level:

| Run | Below 0.6 | 0.6 to 0.85 | 0.85 and up |
|---|---|---|---|
| qwen2.5:3b v6 | 10 of 12 right | 8 of 13 right | 14 of 15 right |

What each review threshold would do: labels below it are shown as "Uncertain, ask your lecturer" (hidden), the rest with their label (shown); wrong counts in brackets:

| Run | Below 0.35: hidden (wrong) / shown (wrong) | Below 0.60: hidden (wrong) / shown (wrong) | Below 0.85: hidden (wrong) / shown (wrong) |
|---|---|---|---|
| qwen2.5:3b v6 | 0 (0) / 40 (8) | 12 (2) / 28 (6) | 25 (7) / 15 (1) |
