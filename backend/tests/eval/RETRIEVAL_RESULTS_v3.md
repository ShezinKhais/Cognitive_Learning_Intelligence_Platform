# Retrieval before and after #127

Embedding model `nomic-embed-text`, captions by `qwen2.5vl:3b` with prompt `caption-v3`. Rank is where the first chunk from a page that answers the question comes; `-` means the material had no chunk from that page at all.

| Questions | hit@1 | hit@5 | MRR |
|---|---|---|---|
| image (5) | 0.00 → 0.20 | 0.00 → 0.60 | 0.00 → 0.40 |
| text (6) | 1.00 → 1.00 | 1.00 → 1.00 | 1.00 → 1.00 |
| all (11) | 0.55 → 0.64 | 0.55 → 0.82 | 0.55 → 0.73 |

| Kind | Question | Answer on | Before: rank (top page) | After: rank (top page) |
|---|---|---|---|---|
| image | What goes wrong when a straight regression line is fitted to 0/1 gender data against height? | 9 | - (8) | 2 (8) |
| image | Plot of the logit function y = exp(b0 + b1 x) / (1 + exp(b0 + b1 x)) | 12 | - (2) | 1 (12) |
| image | Fitted probabilities from the logistic model plotted against height | 15, 16 | - (2) | 14 (2) |
| image | S-shaped logistic curve drawn over the jittered gender points | 16 | - (4) | 3 (9) |
| image | At around what height does the predicted probability of being female fall to one half? | 15, 16 | - (4) | 12 (9) |
| text | What are the three types of logistic regression? | 5 | 1 (5) | 1 (5) |
| text | Why are the beta estimates exponentiated into odds ratios? | 4 | 1 (4) | 1 (4) |
| text | Is logistic regression a discriminative or a generative model? | 6 | 1 (6) | 1 (6) |
| text | Examples of categorical response variables | 7 | 1 (7) | 1 (7) |
| text | What is the mean of a 0/1 indicator variable? | 10 | 1 (10) | 1 (10) |
| text | R output of glm(Gender ~ Hgt, family = binomial) with its coefficients | 13, 14 | 1 (13) | 1 (13) |
