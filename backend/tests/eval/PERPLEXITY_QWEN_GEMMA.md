# Perplexity

Perplexity of each sample lecture's chunks, pooled by token. Lower is more predictable to the model. Everyday English is the reference for ordinary writing; lecture.pptx as PDF has the same words as lecture.pptx, so the pair shows the effect of the file format alone.

Perplexity (per token; compare only models with the same tokenizer):

| Model | everyday English | cnn_lecture.pptx | lecture.docx | lecture.pdf | lecture.pptx | lecture.txt | linear_regression_notes.pdf | lecture.pptx as PDF |
|---|---|---|---|---|---|---|---|---|
| Qwen/Qwen2.5-1.5B | 14.12 | 10.35 | 13.48 | 20.11 | 9.89 | 5.52 | 11.61 | 10.97 |
| google/gemma-3-1b-pt | 13.78 | 19.20 | 20.80 | 32.52 | 14.85 | 9.97 | 19.35 | 17.05 |

Bits per byte (per byte of text; compares any models):

| Model | everyday English | cnn_lecture.pptx | lecture.docx | lecture.pdf | lecture.pptx | lecture.txt | linear_regression_notes.pdf | lecture.pptx as PDF |
|---|---|---|---|---|---|---|---|---|
| Qwen/Qwen2.5-1.5B | 0.812 | 0.819 | 0.840 | 1.031 | 0.766 | 0.518 | 0.730 | 0.876 |
| google/gemma-3-1b-pt | 0.814 | 1.034 | 0.932 | 1.208 | 0.921 | 0.705 | 0.897 | 1.045 |
