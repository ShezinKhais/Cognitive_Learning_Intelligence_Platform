# Retrieval before and after #127

Embedding model `mxbai-embed-large`, captions by `qwen2.5vl:3b` with prompt `caption-v2`. Rank is where the first chunk from a page that answers the question comes; `-` means the material had no chunk from that page at all. precision@5 is the share of the top 5 chunks that come from an answering page.

| Questions | hit@1 | hit@5 | MRR | precision@5 |
|---|---|---|---|---|
| image (5) | 0.00 → 0.40 | 0.00 → 0.80 | 0.00 → 0.56 | 0.00 → 0.16 |
| text (27) | 0.96 → 0.96 | 0.96 → 0.96 | 0.97 → 0.97 | 0.33 → 0.33 |
| lecture.pptx (11) | 0.55 → 0.73 | 0.55 → 0.91 | 0.55 → 0.80 | 0.27 → 0.35 |
| cnn_lecture.pptx (11) | 0.91 → 0.91 | 0.91 → 0.91 | 0.92 → 0.92 | 0.18 → 0.18 |
| linear_regression_notes.pdf (10) | 1.00 → 1.00 | 1.00 → 1.00 | 1.00 → 1.00 | 0.40 → 0.40 |
| all (32) | 0.81 → 0.88 | 0.81 → 0.94 | 0.82 → 0.90 | 0.28 → 0.31 |

| Material | Kind | Question | Answer on | Before: rank (top page) | After: rank (top page) |
|---|---|---|---|---|---|
| lecture.pptx | image | What goes wrong when a straight regression line is fitted to 0/1 gender data against height? | 9 | - (8) | 3 (8) |
| lecture.pptx | image | Plot of the logit function y = exp(b0 + b1 x) / (1 + exp(b0 + b1 x)) | 12 | - (11) | 1 (12) |
| lecture.pptx | image | Fitted probabilities from the logistic model plotted against height | 15, 16 | - (8) | 1 (15) |
| lecture.pptx | image | S-shaped logistic curve drawn over the jittered gender points | 16 | - (14) | 3 (9) |
| lecture.pptx | image | At around what height does the predicted probability of being female fall to one half? | 15, 16 | - (8) | 8 (8) |
| lecture.pptx | text | What are the three types of logistic regression? | 5 | 1 (5) | 1 (5) |
| lecture.pptx | text | Why are the beta estimates exponentiated into odds ratios? | 4 | 1 (4) | 1 (4) |
| lecture.pptx | text | Is logistic regression a discriminative or a generative model? | 6 | 1 (6) | 1 (6) |
| lecture.pptx | text | Examples of categorical response variables | 7 | 1 (7) | 1 (7) |
| lecture.pptx | text | What is the mean of a 0/1 indicator variable? | 10 | 1 (10) | 1 (10) |
| lecture.pptx | text | R output of glm(Gender ~ Hgt, family = binomial) with its coefficients | 13, 14 | 1 (14) | 1 (14) |
| cnn_lecture.pptx | text | Why would a fully connected network on megapixel photos need around a billion parameters? | 2 | 1 (2) | 1 (2) |
| cnn_lecture.pptx | text | What does translation invariance mean for the first layers of a vision network? | 3 | 1 (3) | 1 (3) |
| cnn_lecture.pptx | text | How is each output value of a 2D cross-correlation computed from the input window and the kernel? | 4 | 1 (4) | 1 (4) |
| cnn_lecture.pptx | text | What shape is the output when a kh by kw kernel is applied to an nh by nw image without padding? | 5 | 1 (5) | 1 (5) |
| cnn_lecture.pptx | text | Which kernel finds vertical edges, and what does it output at an edge from white to black? | 6 | 1 (6) | 1 (6) |
| cnn_lecture.pptx | text | How do extra zero pixels around the border stop the image shrinking after many convolutions? | 7 | 1 (7) | 1 (7) |
| cnn_lecture.pptx | text | Why do CNN designers prefer kernel sizes like 3, 5 or 7? | 8 | 1 (8) | 1 (8) |
| cnn_lecture.pptx | text | What happens when the convolution window moves more than one pixel at a time? | 9 | 10 (4) | 10 (4) |
| cnn_lecture.pptx | text | What is the difference between max pooling and average pooling? | 10 | 1 (10) | 1 (10) |
| cnn_lecture.pptx | text | Does a pooling layer have any learnable weights? | 10 | 1 (10) | 1 (10) |
| cnn_lecture.pptx | text | How many output channels does pooling give for an input with several channels? | 11 | 1 (11) | 1 (11) |
| linear_regression_notes.pdf | text | In the house price example, what are the features and what is the label? | 1 | 1 (1) | 1 (1) |
| linear_regression_notes.pdf | text | What does linear regression assume about the noise in the target? | 2 | 1 (2) | 1 (2) |
| linear_regression_notes.pdf | text | Why does the model need a bias term and not only weights? | 3 | 1 (3) | 1 (3) |
| linear_regression_notes.pdf | text | Why is the squared error loss sensitive to outliers? | 4 | 1 (4) | 1 (4) |
| linear_regression_notes.pdf | text | When is the closed-form least squares solution unique? | 5 | 1 (5) | 1 (5) |
| linear_regression_notes.pdf | text | What minibatch size is a sensible starting point for SGD? | 6 | 1 (6) | 1 (6) |
| linear_regression_notes.pdf | text | Are the learning rate and the batch size learned during training? | 6 | 1 (6) | 1 (6) |
| linear_regression_notes.pdf | text | Why is one vectorised addition faster than a Python for-loop over the elements? | 7 | 1 (7) | 1 (7) |
| linear_regression_notes.pdf | text | Why does minimising squared error give the maximum likelihood estimate? | 8 | 1 (8) | 1 (8) |
| linear_regression_notes.pdf | text | How many layers does linear regression have when drawn as a neural network? | 9 | 1 (9) | 1 (9) |
