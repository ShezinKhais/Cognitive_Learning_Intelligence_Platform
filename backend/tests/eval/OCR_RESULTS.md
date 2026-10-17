# OCR accuracy

Tesseract (tesseract, language `eng`) on two lectures saved as image-only scans, scored against each page's true text from the original PDF, after lower-casing and removing punctuation. Word recall is the share of the true words OCR found, in any order; higher is better. CER and WER are the edits needed to reach the true text, over its length; lower is better. They also count as errors text OCR reads that the text layer lacks, such as the university logo on every slide and chart labels, and words read in a different order on two-column slides. A page is read when OCR finds at least 20 letters or digits on it. The poor scan is half the resolution, blurred, tilted 1.5 degrees and saved as a low quality JPEG.

| Document | Scan | Pages read | Word recall | CER | WER | Seconds per page |
|---|---|---|---|---|---|---|
| Computer vision slides (21 pages) | clean, 150 dpi | 21 of 21 | 84.2% | 5.0% | 22.1% | 0.4 |
| Computer vision slides (21 pages) | poor | 20 of 21 | 41.9% | 30.0% | 62.7% | 0.3 |
| Logistic regression slides (18 pages) | clean, 150 dpi | 18 of 18 | 95.7% | 15.3% | 21.7% | 0.6 |
| Logistic regression slides (18 pages) | poor | 16 of 18 | 90.0% | 11.1% | 17.8% | 0.4 |
