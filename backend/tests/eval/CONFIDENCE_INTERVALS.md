# Confidence intervals

95% percentile bootstrap intervals, 10,000 resamples with a fixed seed. Each item (a question, a draft, an answer) is resampled whole, so before and after ranks and human and model labels stay paired. A wide interval means the test set is too small to pin the score down; an interval for a gain that stays above 0 means the gain is unlikely to be chance.

| Measure | Value | 95% interval | n |
|---|---|---|---|
| Retrieval hit@5, before captions | 0.81 | 0.66 to 0.94 | 32 |
| Retrieval hit@5, after captions | 0.91 | 0.78 to 1.00 | 32 |
| Retrieval hit@5, gain from captions | 0.09 | 0.00 to 0.22 | 32 |
| Retrieval MRR, after captions | 0.88 | 0.77 to 0.97 | 32 |
| Retrieval MRR, gain from captions | 0.06 | 0.01 to 0.14 | 32 |
| Grounding: drafts passing the checks | 36% | 20% to 56% | 25 |
| Grounding precision (accepted, judged correct) | 67% | 33% to 100% | 9 |
| Marking accuracy, qwen2.5:3b run 2 (all 40) | 68% | 52% to 82% | 40 |
| Marking macro F1, qwen2.5:3b run 2 (replies read) | 0.79 | 0.62 to 0.93 | 33 |
| Marking accuracy, qwen2.5:7b run 1 (all 40) | 68% | 52% to 82% | 40 |
| Marking macro F1, qwen2.5:7b run 1 (replies read) | 0.78 | 0.62 to 0.91 | 34 |
| Marking accuracy, qwen2.5:7b run 2 (all 40) | 78% | 65% to 90% | 40 |
| Marking macro F1, qwen2.5:7b run 2 (replies read) | 0.82 | 0.67 to 0.94 | 37 |
| Marking accuracy, qwen2.5:3b, schema replies (v4) (all 40) | 78% | 65% to 90% | 40 |
| Marking macro F1, qwen2.5:3b, schema replies (v4) (replies read) | 0.76 | 0.61 to 0.89 | 40 |
| Cohen's kappa, Luna vs Nour | 0.85 | 0.70 to 0.96 | 40 |
