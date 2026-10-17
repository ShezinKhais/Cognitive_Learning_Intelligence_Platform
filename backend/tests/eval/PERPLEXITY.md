# Perplexity

Perplexity of each sample lecture's chunks, pooled by token. Lower is more predictable to the model. Everyday English is the reference for ordinary writing; lecture.pptx as PDF has the same words as lecture.pptx, so the pair shows the effect of the file format alone.

| Model | everyday English | lecture.docx | lecture.pdf | lecture.pptx | lecture.txt | lecture.pptx as PDF |
|---|---|---|---|---|---|---|
| Qwen/Qwen2.5-0.5B | 18.21 | 20.25 | 33.62 | 11.62 | 7.82 | 13.16 |
| Qwen/Qwen2.5-1.5B | 14.12 | 13.48 | 20.11 | 9.89 | 5.52 | 10.97 |
