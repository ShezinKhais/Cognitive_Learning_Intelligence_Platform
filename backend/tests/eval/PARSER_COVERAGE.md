# Parser coverage

Each sample read as an upload would be, with images. Pages with text counts pages or slides with any text, heading or table; Word and text files count as one page.

| File | Parser | Read OK | Pages with text | Headings (with level) | Images | Letter-spaced | Time (s) |
|---|---|---|---|---|---|---|---|
| cnn_lecture.pptx | python-pptx | yes | 12 of 12 | 12 (0) | 0 | no | 0.09 |
| lecture.docx | python-docx | yes | 1 of 1 | 0 (0) | 0 | no | 0.05 |
| lecture.pdf | pypdf | yes | 21 of 21 | 0 (0) | 0 | no | 0.41 |
| lecture.pptx | python-pptx | yes | 17 of 18 | 17 (0) | 4 | no | 0.07 |
| lecture.txt | plain-text | yes | 1 of 1 | 0 (0) | 0 | no | 0.0 |
| linear_regression_notes.pdf | pypdf | yes | 11 of 11 | 0 (0) | 0 | no | 0.07 |
| scanned.pdf | pypdf+ocr | yes | 1 of 1 | 0 (0) | 0 | no | 0.23 |
| corrupt.pdf | - | no: ValidationError: This file could not be read; it may be corrupt or not a real document. | - | - | - | - | 0.0 |
