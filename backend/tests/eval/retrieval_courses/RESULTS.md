# Retrieval across whole courses (#252)

Embedding model `nomic-embed-text`, captions by `qwen2.5vl:3b` (prompt `caption-v2`), commit `0a80e16`, run on 2026-11-11. Each question searches every chunk of its course, as the tutor does. The tutor's cutoff is now 0.65.

| Course | Material | SHA-256 (first 12) | Read with | Chunks |
|---|---|---|---|---|
| 6.0002 data science | MIT6_0002F16_lec3.pdf | `9975afd92af7` | pypdf | 64 |
| 6.0002 data science | MIT6_0002F16_lec6.pdf | `74730cafc414` | pypdf | 42 |
| 18.650 statistics | MIT18_650F16_Regression.pdf | `b228e310c460` | pypdf | 46 |
| 18.650 statistics | MIT18_650F16_Maximum_LE.pdf | `b088a9dc1d3f` | pypdf | 28 |
| 6.007 electromagnetics | MIT6_007S11_lec01.pptx | `7450b49c09a1` | python-pptx | 54 |
| 6.007 electromagnetics | MIT6_007S11_lec02.pptx | `06e384c4f996` | python-pptx | 65 |
| 6.007 electromagnetics | MIT6_007S11_lec04.pptx | `5305892adb39` | python-pptx | 60 |
| 6.007 electromagnetics | MIT6_007S11_lec08.pptx | `e1f782f80fcc` | python-pptx | 51 |
| 6.033 systems | MIT6_033S18lec8.pdf | `3560f658785d` | pypdf | 16 |
| 18.404 theory of computation | MIT18_404f20_lec6.pptx | `7109395e12e4` | python-pptx | 15 |

## Finding the right page

Answerable questions only. A share is followed by its 95% interval; with few questions per row, the intervals are wide.

| Questions | n | Right page on top | Right page in top 5 | MRR | precision@5 | Right lecture on top |
|---|---|---|---|---|---|---|
| text: answered by the page's text | 57 | 42 of 57 (74%, 61% to 83%) | 50 of 57 (88%, 77% to 94%) | 0.81 | 0.29 | 54 of 57 (95%, 86% to 98%) |
| diagram: answered by a diagram | 9 | 6 of 9 (67%, 35% to 88%) | 7 of 9 (78%, 45% to 94%) | 0.73 | 0.42 | 9 of 9 (100%, 70% to 100%) |
| table: answered by a table | 3 | 2 of 3 (67%, 21% to 94%) | 2 of 3 (67%, 21% to 94%) | 0.67 | 0.27 | 3 of 3 (100%, 44% to 100%) |
| image-only: answered only by a picture, photo or plot | 11 | 5 of 11 (45%, 21% to 72%) | 7 of 11 (64%, 35% to 85%) | 0.54 | 0.16 | 11 of 11 (100%, 74% to 100%) |
| formula: about a formula or its symbols | 20 | 15 of 20 (75%, 53% to 89%) | 18 of 20 (90%, 70% to 97%) | 0.81 | 0.31 | 20 of 20 (100%, 84% to 100%) |
| code: about code or program output | 7 | 6 of 7 (86%, 49% to 97%) | 6 of 7 (86%, 49% to 97%) | 0.88 | 0.20 | 7 of 7 (100%, 65% to 100%) |
| student-wording: worded as a student would, not as the slide is | 17 | 8 of 17 (47%, 26% to 69%) | 13 of 17 (76%, 53% to 90%) | 0.60 | 0.21 | 16 of 17 (94%, 73% to 99%) |
| arabic: asked in Arabic | 3 | 0 of 3 (0%, 0% to 56%) | 1 of 3 (33%, 6% to 79%) | 0.12 | 0.07 | 2 of 3 (67%, 21% to 94%) |
| course: 6.0002 data science | 33 | 18 of 33 (55%, 38% to 70%) | 23 of 33 (70%, 53% to 83%) | 0.62 | 0.18 | 30 of 33 (91%, 76% to 97%) |
| course: 18.650 statistics | 27 | 18 of 27 (67%, 48% to 81%) | 22 of 27 (81%, 63% to 92%) | 0.75 | 0.21 | 26 of 27 (96%, 82% to 99%) |
| course: 6.007 electromagnetics | 34 | 26 of 34 (76%, 60% to 88%) | 31 of 34 (91%, 77% to 97%) | 0.82 | 0.40 | 34 of 34 (100%, 90% to 100%) |
| course: 6.033 systems | 7 | 6 of 7 (86%, 49% to 97%) | 7 of 7 (100%, 65% to 100%) | 0.93 | 0.37 | 7 of 7 (100%, 65% to 100%) |
| course: 18.404 theory of computation | 8 | 7 of 8 (88%, 53% to 98%) | 7 of 8 (88%, 53% to 98%) | 0.88 | 0.33 | 8 of 8 (100%, 68% to 100%) |
| split: dev | 74 | 49 of 74 (66%, 55% to 76%) | 61 of 74 (82%, 72% to 89%) | 0.74 | 0.25 | 72 of 74 (97%, 91% to 99%) |
| split: heldout | 35 | 26 of 35 (74%, 58% to 86%) | 29 of 35 (83%, 67% to 92%) | 0.79 | 0.34 | 33 of 35 (94%, 81% to 98%) |
| all | 109 | 75 of 109 (69%, 60% to 77%) | 90 of 109 (83%, 74% to 89%) | 0.75 | 0.28 | 105 of 109 (96%, 91% to 99%) |

## Saying "not in the material"

The tutor drops every excerpt further than the cutoff from the question. When all of them are dropped it says the material does not cover it (abstains). It should abstain on off-topic and other-course questions, and answer the rest.

| Questions | Cutoff | Abstained when nothing answers | Wrongly abstained when a page answers | Balanced accuracy |
|---|---|---|---|---|
| all, current setting | 0.65 | 0 of 22 (0%, 0% to 15%) | 0 of 109 (0%, 0% to 3%) | 0.50 |
| dev, current setting | 0.65 | 0 of 16 (0%, 0% to 19%) | 0 of 74 (0%, 0% to 5%) | 0.50 |
| dev, best cutoff on dev | 0.43 | 16 of 16 (100%, 81% to 100%) | 3 of 74 (4%, 1% to 11%) | 0.98 |
| **held-out, current setting** | 0.65 | 0 of 6 (0%, 0% to 39%) | 0 of 35 (0%, 0% to 10%) | 0.50 |
| **held-out, cutoff chosen on dev** | 0.43 | 6 of 6 (100%, 61% to 100%) | 2 of 35 (6%, 2% to 19%) | 0.97 |

The cutoff chosen on the dev questions is **0.43** (now 0.65). Only the held-out rows say how it would do on questions nobody tuned on.

## Every question

Rank of the first excerpt from an answering page (`-`: none in the course); the top excerpt as lecture, page and distance.

| Id | Split | Kinds | Question | Answer on | Rank | Top excerpt |
|---|---|---|---|---|---|---|
| c001 | dev | text | What are the two things every graph is made of? | MIT6_0002F16_lec3.pdf p.4, 5 | 9 | MIT6_0002F16_lec3.pdf p.22, 0.377 |
| c002 | heldout | diagram | Drawing of a directed graph whose edges carry weights like 10, 3 and 12 | MIT6_0002F16_lec3.pdf p.5 | 9 | MIT6_0002F16_lec3.pdf p.20, 0.371 |
| c003 | dev | text, student-wording | Why is a tree just a special kind of graph? | MIT6_0002F16_lec3.pdf p.7 | 1 | MIT6_0002F16_lec3.pdf p.7, 0.370 |
| c004 | heldout | image-only | Street map of Boston traffic used to show why graphs are useful | MIT6_0002F16_lec3.pdf p.10 | 42 | MIT6_0002F16_lec3.pdf p.22, 0.334 |
| c005 | heldout | text | The bridges of Konigsberg problem from 1735 | MIT6_0002F16_lec3.pdf p.12, 13 | 1 | MIT6_0002F16_lec3.pdf p.12, 0.410 |
| c006 | heldout | text, student-wording | How did Euler turn the Konigsberg bridges into a graph, and could you cross every bridge once? | MIT6_0002F16_lec3.pdf p.13 | 6 | MIT6_0002F16_lec6.pdf p.3, 0.391 |
| c007 | dev | code | Python class for an edge with a source node and a destination node | MIT6_0002F16_lec3.pdf p.16 | 1 | MIT6_0002F16_lec3.pdf p.16, 0.290 |
| c008 | dev | code | How does the Digraph class store its edges? A dictionary from each node to a list of children | MIT6_0002F16_lec3.pdf p.18 | 1 | MIT6_0002F16_lec3.pdf p.18, 0.156 |
| c009 | dev | text | Adjacency matrix versus adjacency list for representing a digraph | MIT6_0002F16_lec3.pdf p.17 | 27 | MIT6_0002F16_lec3.pdf p.18, 0.362 |
| c010 | dev | text | Why is Graph a subclass of Digraph and not the other way round? | MIT6_0002F16_lec3.pdf p.20 | 1 | MIT6_0002F16_lec3.pdf p.20, 0.258 |
| c011 | heldout | diagram | Example graph of cities: Boston, Providence, New York, Chicago, Denver, Phoenix and Los Angeles | MIT6_0002F16_lec3.pdf p.23, 29 | 8 | MIT6_0002F16_lec3.pdf p.24, 0.291 |
| c012 | heldout | text | How does depth-first search avoid going round in cycles? | MIT6_0002F16_lec3.pdf p.25, 26, 27 | 3 | MIT6_0002F16_lec3.pdf p.33, 0.451 |
| c013 | dev | code | Recursive DFS function with a shortestPath wrapper that starts the recursion | MIT6_0002F16_lec3.pdf p.27 | 1 | MIT6_0002F16_lec3.pdf p.27, 0.242 |
| c014 | dev | text | How is breadth-first search different from depth-first search? | MIT6_0002F16_lec3.pdf p.32, 33 | 2 | MIT6_0002F16_lec6.pdf p.9, 0.503 |
| c015 | dev | code | Printed output of breadth-first search finding the path from Boston to Phoenix | MIT6_0002F16_lec3.pdf p.34, 35 | 6 | MIT6_0002F16_lec3.pdf p.28, 0.365 |
| c016 | heldout | text, student-wording | Why can't BFS find the cheapest path when edges have weights? | MIT6_0002F16_lec3.pdf p.36 | 53 | MIT6_0002F16_lec3.pdf p.33, 0.317 |
| c017 | dev | text, student-wording | Who came up with Monte Carlo simulation and what game was he playing? | MIT6_0002F16_lec6.pdf p.3 | 4 | MIT6_0002F16_lec6.pdf p.1, 0.263 |
| c018 | dev | text | Difference between a population and a sample in inferential statistics | MIT6_0002F16_lec6.pdf p.4 | 1 | MIT6_0002F16_lec6.pdf p.4, 0.246 |
| c019 | dev | image-only | Picture of a hundred coins that were flipped | MIT6_0002F16_lec6.pdf p.7, 8 | 3 | MIT6_0002F16_lec6.pdf p.5, 0.258 |
| c020 | dev | text, student-wording | Why should I trust 100 coin flips more than 2? | MIT6_0002F16_lec6.pdf p.9 | 11 | MIT6_0002F16_lec6.pdf p.8, 0.179 |
| c021 | dev | code | FairRoulette class with 36 pockets and a spin method | MIT6_0002F16_lec6.pdf p.11 | 1 | MIT6_0002F16_lec6.pdf p.11, 0.207 |
| c022 | heldout | code | Expected return after 100 spins compared with a million spins of fair roulette | MIT6_0002F16_lec6.pdf p.13 | 1 | MIT6_0002F16_lec6.pdf p.13, 0.133 |
| c023 | dev | text | Definition of the law of large numbers | MIT6_0002F16_lec6.pdf p.14 | 1 | MIT6_0002F16_lec6.pdf p.14, 0.342 |
| c024 | heldout | text, student-wording | If black came up 26 times in a row, is red now more likely? | MIT6_0002F16_lec6.pdf p.15 | 1 | MIT6_0002F16_lec6.pdf p.15, 0.282 |
| c025 | heldout | text | Regression to the mean after ten red spins in a row | MIT6_0002F16_lec6.pdf p.16 | 1 | MIT6_0002F16_lec6.pdf p.16, 0.230 |
| c026 | dev | code | European and American roulette subclasses that add pockets 0 and 00 | MIT6_0002F16_lec6.pdf p.18 | 1 | MIT6_0002F16_lec6.pdf p.18, 0.140 |
| c027 | dev | formula | Formula for the variance and the standard deviation of a set of values | MIT6_0002F16_lec6.pdf p.21, 22 | 1 | MIT6_0002F16_lec6.pdf p.21, 0.315 |
| c028 | dev | text, student-wording | What does it actually mean to say plus or minus 3.5% with 95% confidence? | MIT6_0002F16_lec6.pdf p.23 | 1 | MIT6_0002F16_lec6.pdf p.23, 0.265 |
| c029 | dev | text | Empirical rule: 68%, 95% and 99.7% of data within one, two and three standard deviations | MIT6_0002F16_lec6.pdf p.24, 30 | 1 | MIT6_0002F16_lec6.pdf p.24, 0.083 |
| c030 | dev | image-only | Bell-shaped plot of the normal distribution with mean 0 and standard deviation 1 | MIT6_0002F16_lec6.pdf p.27, 30 | 1 | MIT6_0002F16_lec6.pdf p.30, 0.270 |
| c031 | dev | formula | Probability density function of the normal distribution | MIT6_0002F16_lec6.pdf p.29, 30 | 1 | MIT6_0002F16_lec6.pdf p.29, 0.296 |
| c032 | heldout | arabic | ما هو قانون الأعداد الكبيرة؟ | MIT6_0002F16_lec6.pdf p.14 | 77 | MIT6_0002F16_lec3.pdf p.10, 0.440 |
| c033 | dev | arabic | ما الفرق بين البحث بالعمق أولاً والبحث بالعرض أولاً في الرسوم البيانية؟ | MIT6_0002F16_lec3.pdf p.25, 26, 32, 33 | 4 | MIT6_0002F16_lec3.pdf p.10, 0.446 |
| c110 | dev | off-topic | What time is the final exam? | nothing | - | MIT6_0002F16_lec6.pdf p.7, 0.508 |
| c111 | heldout | other-course | What do Maxwell's equations say about magnetic flux? | nothing | - | MIT6_0002F16_lec3.pdf p.32, 0.541 |
| c112 | dev | other-course | What is the Church-Turing thesis? | nothing | - | MIT6_0002F16_lec3.pdf p.38, 0.442 |
| c113 | heldout | off-topic | Who won the 2022 football World Cup? | nothing | - | MIT6_0002F16_lec3.pdf p.10, 0.566 |
| c114 | dev | off-topic, arabic | متى موعد الامتحان النهائي؟ | nothing | - | MIT6_0002F16_lec3.pdf p.10, 0.457 |
| c115 | dev | other-course | How was the ARPANET connected in 1977? | nothing | - | MIT6_0002F16_lec3.pdf p.22, 0.495 |
| c034 | dev | image-only | Scatter plot of random points (Xi, Yi) used to introduce linear regression | MIT18_650F16_Regression.pdf p.2, 8 | 1 | MIT18_650F16_Regression.pdf p.2, 0.193 |
| c035 | heldout | text | Linear regression shows correlation, not causality | MIT18_650F16_Regression.pdf p.23 | 1 | MIT18_650F16_Regression.pdf p.23, 0.167 |
| c036 | heldout | formula | Least squares estimator of the intercept a and slope b | MIT18_650F16_Regression.pdf p.12 | 1 | MIT18_650F16_Regression.pdf p.12, 0.276 |
| c037 | dev | formula | beta hat equals (X transpose X) inverse times X transpose Y | MIT18_650F16_Regression.pdf p.15, 16 | 55 | MIT18_650F16_Regression.pdf p.19, 0.411 |
| c038 | heldout | text | What does homoscedastic noise mean in the Gaussian regression model? | MIT18_650F16_Regression.pdf p.17 | 1 | MIT18_650F16_Regression.pdf p.17, 0.276 |
| c039 | dev | text, student-wording | How do I test whether one explanatory variable actually matters? | MIT18_650F16_Regression.pdf p.19 | 2 | MIT18_650F16_Regression.pdf p.20, 0.284 |
| c040 | dev | text | Bonferroni test for whether a group of explanatory variables is significant | MIT18_650F16_Regression.pdf p.20 | 1 | MIT18_650F16_Regression.pdf p.20, 0.212 |
| c041 | heldout | formula | Fisher distribution with p and q degrees of freedom | MIT18_650F16_Regression.pdf p.22 | 1 | MIT18_650F16_Regression.pdf p.22, 0.213 |
| c042 | dev | text, student-wording | What goes wrong when there are more variables than observations? | MIT18_650F16_Regression.pdf p.24, 27 | 14 | MIT18_650F16_Regression.pdf p.14, 0.356 |
| c043 | dev | formula | Lasso estimator with an L1 penalty | MIT18_650F16_Regression.pdf p.30 | 1 | MIT18_650F16_Regression.pdf p.30, 0.384 |
| c044 | dev | image-only | Plot of the coefficient paths as lambda changes | MIT18_650F16_Regression.pdf p.32 | 1 | MIT18_650F16_Regression.pdf p.32, 0.377 |
| c045 | heldout | text | Mallow's Cp, AIC and BIC as choices of the penalty lambda | MIT18_650F16_Regression.pdf p.29 | 1 | MIT18_650F16_Regression.pdf p.29, 0.280 |
| c046 | heldout | text | How to choose the bandwidth h in nonparametric regression | MIT18_650F16_Regression.pdf p.39, 43 | 2 | MIT18_650F16_Regression.pdf p.36, 0.227 |
| c047 | dev | image-only | Local average estimate that is a flat line because h is too big | MIT18_650F16_Regression.pdf p.41 | 8 | MIT18_650F16_Regression.pdf p.35, 0.378 |
| c048 | dev | text | Estimate f(x) by averaging the Yi whose Xi are close to x | MIT18_650F16_Regression.pdf p.35, 36 | 1 | MIT18_650F16_Regression.pdf p.35, 0.250 |
| c049 | dev | formula | Definition of the total variation distance between two probability distributions | MIT18_650F16_Maximum_LE.pdf p.2, 3, 4 | 2 | MIT18_650F16_Maximum_LE.pdf p.5, 0.171 |
| c050 | dev | text | Properties of total variation: symmetric, positive, definite, triangle inequality | MIT18_650F16_Maximum_LE.pdf p.5 | 1 | MIT18_650F16_Maximum_LE.pdf p.5, 0.184 |
| c051 | dev | text, student-wording | Is the KL divergence a real distance? | MIT18_650F16_Maximum_LE.pdf p.9 | 1 | MIT18_650F16_Maximum_LE.pdf p.9, 0.209 |
| c052 | dev | formula | Kullback-Leibler divergence formula with the log of the ratio of densities | MIT18_650F16_Maximum_LE.pdf p.8 | 3 | MIT18_650F16_Maximum_LE.pdf p.10, 0.159 |
| c053 | dev | text | Minimising the estimated KL divergence gives the maximum likelihood principle | MIT18_650F16_Maximum_LE.pdf p.11 | 1 | MIT18_650F16_Maximum_LE.pdf p.11, 0.153 |
| c054 | dev | formula | Hessian matrix and when a multivariate function is concave | MIT18_650F16_Maximum_LE.pdf p.14 | 1 | MIT18_650F16_Maximum_LE.pdf p.14, 0.254 |
| c055 | heldout | formula | Likelihood of Bernoulli trials | MIT18_650F16_Maximum_LE.pdf p.17 | 1 | MIT18_650F16_Maximum_LE.pdf p.17, 0.258 |
| c056 | heldout | formula | Likelihood of the Poisson model | MIT18_650F16_Maximum_LE.pdf p.18 | 1 | MIT18_650F16_Maximum_LE.pdf p.18, 0.193 |
| c057 | heldout | text | Maximum likelihood estimators for the Gaussian model are the sample mean and sample variance | MIT18_650F16_Maximum_LE.pdf p.20, 22 | 1 | MIT18_650F16_Maximum_LE.pdf p.22, 0.253 |
| c058 | dev | formula | Definition of the Fisher information | MIT18_650F16_Maximum_LE.pdf p.23 | 1 | MIT18_650F16_Maximum_LE.pdf p.23, 0.292 |
| c059 | dev | text | Conditions under which the MLE is consistent and asymptotically normal | MIT18_650F16_Maximum_LE.pdf p.24 | 9 | MIT18_650F16_Regression.pdf p.20, 0.412 |
| c060 | dev | arabic | ما هو مقدّر الإمكان الأعظم؟ | MIT18_650F16_Maximum_LE.pdf p.21 | 10 | MIT18_650F16_Maximum_LE.pdf p.12, 0.518 |
| c116 | dev | other-course | How does depth-first search find a path between cities? | nothing | - | MIT18_650F16_Maximum_LE.pdf p.7, 0.507 |
| c117 | dev | off-topic | Recipe for chocolate cake | nothing | - | MIT18_650F16_Maximum_LE.pdf p.15, 0.607 |
| c118 | heldout | other-course | How does an iPhone accelerometer detect rotation? | nothing | - | MIT18_650F16_Regression.pdf p.19, 0.552 |
| c119 | dev | other-course | How does a solenoid ring a doorbell? | nothing | - | MIT18_650F16_Maximum_LE.pdf p.14, 0.557 |
| c061 | dev | table | iPhone technical specifications: memory, processor and battery | MIT6_007S11_lec01.pptx p.2 | 1 | MIT6_007S11_lec01.pptx p.2, 0.164 |
| c062 | heldout | diagram, student-wording | How does a touch screen know where my finger is? | MIT6_007S11_lec01.pptx p.5, 10 | 3 | MIT6_007S11_lec01.pptx p.8, 0.290 |
| c063 | heldout | diagram | Accelerometer made of a mass on springs between fixed plates | MIT6_007S11_lec01.pptx p.7, 8, 10 | 1 | MIT6_007S11_lec01.pptx p.7, 0.260 |
| c064 | heldout | diagram | Layers of a liquid crystal display: polarizer, glass, color filter, backlight | MIT6_007S11_lec01.pptx p.11, 12 | 1 | MIT6_007S11_lec01.pptx p.11, 0.156 |
| c065 | dev | diagram | CMOS image sensor pixel with microlens, color filter and photodiode | MIT6_007S11_lec01.pptx p.14, 15, 16 | 1 | MIT6_007S11_lec01.pptx p.14, 0.335 |
| c066 | dev | diagram | MOSFET transistor with source, drain and control gate | MIT6_007S11_lec01.pptx p.18 | 1 | MIT6_007S11_lec01.pptx p.18, 0.196 |
| c067 | heldout | formula | Capacitance C equals epsilon times A over d | MIT6_007S11_lec01.pptx p.3, 5 | 1 | MIT6_007S11_lec01.pptx p.3, 0.261 |
| c068 | heldout | table | How is 6.007 graded: labs, problem sets, midterms and final? | MIT6_007S11_lec01.pptx p.27 | 1 | MIT6_007S11_lec01.pptx p.27, 0.415 |
| c069 | dev | table | Table matching each iPhone component to a 6.007 concept | MIT6_007S11_lec01.pptx p.23, 24 | - | MIT6_007S11_lec01.pptx p.2, 0.257 |
| c070 | heldout | text, student-wording | How many hours of video can the iPhone battery play? | MIT6_007S11_lec01.pptx p.29 | 1 | MIT6_007S11_lec01.pptx p.29, 0.288 |
| c071 | dev | text, student-wording | What does one joule feel like in everyday life? | MIT6_007S11_lec02.pptx p.4 | 1 | MIT6_007S11_lec02.pptx p.4, 0.187 |
| c072 | heldout | text | First law of thermodynamics: energy is conserved | MIT6_007S11_lec02.pptx p.6, 7 | 1 | MIT6_007S11_lec02.pptx p.6, 0.140 |
| c073 | heldout | text | Where friction comes from at the atomic level | MIT6_007S11_lec02.pptx p.10, 11, 12 | 1 | MIT6_007S11_lec02.pptx p.12, 0.146 |
| c074 | heldout | text | Who was James Prescott Joule? | MIT6_007S11_lec02.pptx p.13 | 1 | MIT6_007S11_lec02.pptx p.13, 0.252 |
| c075 | dev | text | How many watts is one horsepower? | MIT6_007S11_lec02.pptx p.17 | 1 | MIT6_007S11_lec02.pptx p.17, 0.283 |
| c076 | heldout | text | Across and through variables, and power as their product | MIT6_007S11_lec02.pptx p.18, 19 | 1 | MIT6_007S11_lec02.pptx p.19, 0.228 |
| c077 | dev | image-only | Chart of non-hydro renewable electricity generation in the USA over time | MIT6_007S11_lec02.pptx p.21 | 1 | MIT6_007S11_lec02.pptx p.21, 0.212 |
| c078 | dev | image-only | Pie chart of solar PV capacity by country | MIT6_007S11_lec02.pptx p.24 | 4 | MIT6_007S11_lec02.pptx p.23, 0.310 |
| c079 | dev | text | Electric go-cart that converts the battery's energy into motion | MIT6_007S11_lec02.pptx p.25 | 1 | MIT6_007S11_lec02.pptx p.25, 0.169 |
| c080 | dev | text, student-wording | Why does gasoline pack so much more energy than a battery? | MIT6_007S11_lec04.pptx p.6, 21 | 5 | MIT6_007S11_lec04.pptx p.3, 0.202 |
| c081 | dev | text | Regenerative brakes in hybrid cars | MIT6_007S11_lec04.pptx p.9 | 1 | MIT6_007S11_lec04.pptx p.9, 0.190 |
| c082 | dev | text, formula | Kirchhoff's current law as conservation of charge at a node | MIT6_007S11_lec04.pptx p.11 | 1 | MIT6_007S11_lec04.pptx p.11, 0.162 |
| c083 | dev | formula | Energy stored in a capacitor is one half C v squared | MIT6_007S11_lec04.pptx p.12, 15 | 1 | MIT6_007S11_lec04.pptx p.12, 0.251 |
| c084 | dev | image-only | Plot of energy density against power density for fuel cells, batteries and capacitors | MIT6_007S11_lec04.pptx p.13, 18, 21 | 13 | MIT6_007S11_lec04.pptx p.12, 0.260 |
| c085 | heldout | text | Galvani, zinc and copper, and how a battery works | MIT6_007S11_lec04.pptx p.20 | 1 | MIT6_007S11_lec04.pptx p.20, 0.217 |
| c086 | dev | formula | Gauss's law: flux through a closed surface equals the charge inside | MIT6_007S11_lec04.pptx p.16 | 1 | MIT6_007S11_lec04.pptx p.16, 0.172 |
| c087 | dev | formula | Magnetic field inside a long solenoid, H = N I / h | MIT6_007S11_lec08.pptx p.6 | 3 | MIT6_007S11_lec08.pptx p.8, 0.224 |
| c088 | dev | image-only | Iron filings showing the magnetic field lines of a bar magnet | MIT6_007S11_lec08.pptx p.8 | 7 | MIT6_007S11_lec08.pptx p.11, 0.233 |
| c089 | dev | text | Uses of solenoids: transformer, speaker, Helmholtz coil | MIT6_007S11_lec08.pptx p.9 | 1 | MIT6_007S11_lec08.pptx p.9, 0.184 |
| c090 | dev | text | How a doorbell uses a solenoid | MIT6_007S11_lec08.pptx p.11 | 2 | MIT6_007S11_lec08.pptx p.9, 0.275 |
| c091 | dev | text | Magnetic field of a toroid and a tape recorder head | MIT6_007S11_lec08.pptx p.12, 13 | 1 | MIT6_007S11_lec08.pptx p.12, 0.279 |
| c092 | dev | text | Neodymium iron boron permanent magnets | MIT6_007S11_lec08.pptx p.14 | 1 | MIT6_007S11_lec08.pptx p.14, 0.146 |
| c093 | dev | formula | Maxwell's equations in differential and integral form | MIT6_007S11_lec01.pptx p.3; MIT6_007S11_lec08.pptx p.4, 23 | 1 | MIT6_007S11_lec08.pptx p.23, 0.191 |
| c094 | dev | text, student-wording | What stops us building an infinitely strong electromagnet? | MIT6_007S11_lec08.pptx p.22 | 1 | MIT6_007S11_lec08.pptx p.22, 0.289 |
| c120 | dev | other-course | What is the maximum likelihood estimator? | nothing | - | MIT6_007S11_lec04.pptx p.11, 0.510 |
| c121 | dev | off-topic | How do I apply for a student visa? | nothing | - | MIT6_007S11_lec01.pptx p.5, 0.547 |
| c122 | heldout | other-course | What is a nondeterministic Turing machine? | nothing | - | MIT6_007S11_lec02.pptx p.7, 0.447 |
| c123 | dev | other-course | Simulating roulette with Python classes | nothing | - | MIT6_007S11_lec02.pptx p.9, 0.488 |
| c095 | heldout | diagram | Network of end points connected through switches and links | MIT6_033S18lec8.pdf p.3, 4, 5, 6, 7 | 1 | MIT6_033S18lec8.pdf p.4, 0.241 |
| c096 | dev | text | What is routing in a network? | MIT6_033S18lec8.pdf p.4, 5, 6 | 1 | MIT6_033S18lec8.pdf p.5, 0.215 |
| c097 | dev | text | Naming and addressing: giving nodes unique addresses | MIT6_033S18lec8.pdf p.3 | 1 | MIT6_033S18lec8.pdf p.3, 0.212 |
| c098 | heldout | image-only | ARPANET logical map from March 1977 | MIT6_033S18lec8.pdf p.9 | 1 | MIT6_033S18lec8.pdf p.9, 0.278 |
| c099 | dev | text | Transport: sharing the network efficiently and fairly and dealing with reliability | MIT6_033S18lec8.pdf p.7 | 1 | MIT6_033S18lec8.pdf p.7, 0.256 |
| c100 | dev | text, student-wording | When did the Internet become commercial? | MIT6_033S18lec8.pdf p.13 | 2 | MIT6_033S18lec8.pdf p.15, 0.331 |
| c101 | dev | text | The Internet was designed to be flexible and robust to failure | MIT6_033S18lec8.pdf p.15 | 1 | MIT6_033S18lec8.pdf p.15, 0.191 |
| c124 | dev | other-course | Energy stored in a capacitor | nothing | - | MIT6_033S18lec8.pdf p.11, 0.582 |
| c125 | dev | off-topic | Best pizza near campus | nothing | - | MIT6_033S18lec8.pdf p.8, 0.598 |
| c126 | dev | other-course | Lasso regression and the choice of lambda | nothing | - | MIT6_033S18lec8.pdf p.10, 0.527 |
| c127 | heldout | off-topic, arabic | كيف أعيد تعيين كلمة مرور الجامعة؟ | nothing | - | MIT6_033S18lec8.pdf p.13, 0.494 |
| c102 | dev | text | Church-Turing thesis: intuitive algorithms equal Turing machines | MIT18_404f20_lec6.pptx p.6 | 1 | MIT18_404f20_lec6.pptx p.6, 0.170 |
| c103 | dev | diagram | Simulating a multi-tape Turing machine on a single tape | MIT18_404f20_lec6.pptx p.3 | 1 | MIT18_404f20_lec6.pptx p.3, 0.154 |
| c104 | dev | text | Nondeterministic Turing machines are no more powerful than deterministic ones | MIT18_404f20_lec6.pptx p.4 | 1 | MIT18_404f20_lec6.pptx p.4, 0.173 |
| c105 | dev | text | Turing enumerator: a Turing machine with a printer | MIT18_404f20_lec6.pptx p.5 | 1 | MIT18_404f20_lec6.pptx p.5, 0.150 |
| c106 | dev | formula | Hilbert's tenth problem and Diophantine equations | MIT18_404f20_lec6.pptx p.7 | 1 | MIT18_404f20_lec6.pptx p.7, 0.150 |
| c107 | dev | formula | Turing machine that recognizes a^k b^k c^k | MIT18_404f20_lec6.pptx p.9 | 14 | MIT18_404f20_lec6.pptx p.4, 0.308 |
| c108 | heldout | text | Notation for encoding objects as strings, written in angle brackets | MIT18_404f20_lec6.pptx p.8 | 1 | MIT18_404f20_lec6.pptx p.8, 0.362 |
| c109 | heldout | text, student-wording | Which of these is true about Alan Turing: codebreaker, banknote, imprisoned? | MIT18_404f20_lec6.pptx p.6 | 1 | MIT18_404f20_lec6.pptx p.6, 0.209 |
| c128 | dev | other-course | Breadth-first search for the shortest path between cities | nothing | - | MIT18_404f20_lec6.pptx p.11, 0.473 |
| c129 | dev | off-topic | How do I reset my university password? | nothing | - | MIT18_404f20_lec6.pptx p.6, 0.522 |
| c130 | dev | other-course | Magnetic field inside a solenoid | nothing | - | MIT18_404f20_lec6.pptx p.8, 0.580 |
| c131 | heldout | other-course | Law of large numbers and the gambler's fallacy | nothing | - | MIT18_404f20_lec6.pptx p.7, 0.478 |
