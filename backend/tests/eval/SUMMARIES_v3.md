# Session summaries

Model `qwen2.5:3b`, prompts `lecturer-summary-v3` and `student-summary-v3`, on the labelled answer set read as 8 students. Each summary ends as the model's on its first try, the model's after one retry with its problems listed, or the plain facts.

| Summary | Written | First try | After one retry | Plain facts |
|---|---|---|---|---|
| Lecturer | 10 | 1 (10%) | 0 (0%) | 9 (90%) |
| Student | 16 | 0 (0%) | 1 (6%) | 15 (94%) |

| Problem in the final failed attempt | Summaries |
|---|---|
| sentence N names none of the topics in the facts | 23 |
| sentence N has N without saying what it counts | 20 |
| N sentences, more than N | 8 |
| N is not in the facts for Types of logistic regression, What is logistic regression | 4 |
| slide N is not one to review for Types of logistic regression, What is logistic regression | 4 |
| N is not in the facts for Binary classification threshold, Interpreting odds ratios | 4 |
| slide N is not one to review for Binary classification threshold, Interpreting odds ratios | 4 |
| N is not in the facts for Binary classification threshold, What is logistic regression | 3 |
| slide N is not one to review for Binary classification threshold, What is logistic regression | 3 |
| N struggling is wrong for Logistic regression and machine learning | 2 |
| N is not in the facts for Logistic regression and machine learning | 2 |
| N is not in the facts for Interpreting odds ratios | 2 |
| leaves out a topic | 2 |
| N is not in the facts for Binary classification threshold, Logistic regression and machine learning, Types of logistic regression | 2 |
| slide N is not one to review for Binary classification threshold, Logistic regression and machine learning, Types of logistic regression | 2 |
| N struggling is wrong for Types of logistic regression, Binary classification threshold | 1 |
| N struggling is wrong for What is logistic regression | 1 |
| N struggling is wrong for Types of logistic regression | 1 |
| N struggling is wrong for Binary classification threshold | 1 |
| N struggling is wrong for Interpreting odds ratios | 1 |
| N is not in the facts for Types of logistic regression | 1 |
| N is not in the facts for Binary classification threshold | 1 |
| N partial is wrong for Interpreting odds ratios | 1 |
| N answers is wrong for Binary classification threshold | 1 |
| N answers is wrong for Types of logistic regression | 1 |
| N mastered is wrong for Logistic regression and machine learning | 1 |
| N is not in the facts for Binary classification threshold, Interpreting odds ratios, Logistic regression and machine learning | 1 |
| slide N is not one to review for Binary classification threshold, Interpreting odds ratios, Logistic regression and machine learning | 1 |
| N is not in the facts for Interpreting odds ratios, Binary classification threshold | 1 |
| slide N is not one to review for Interpreting odds ratios, Binary classification threshold | 1 |
| calls Binary classification threshold partial, but it is struggling | 1 |
| slide N is not one to review for Binary classification threshold | 1 |
| slide N is not one to review for Interpreting odds ratios | 1 |
| slide N is not one to review for Logistic regression and machine learning | 1 |
| N is not in the facts for What is logistic regression, Binary classification threshold | 1 |
| slide N is not one to review for What is logistic regression, Binary classification threshold | 1 |
| N is not in the facts for Interpreting odds ratios, Logistic regression and machine learning | 1 |
| calls Interpreting odds ratios partial, but it is struggling | 1 |
| slide N is not one to review for Interpreting odds ratios, Logistic regression and machine learning | 1 |

## Examples

Lecturer (plain facts):

> What is logistic regression: medium. 8 answers: 2 mastered, 2 partial, 4 struggling.
> Logistic regression and machine learning: medium. 8 answers: 2 mastered, 3 partial, 3 struggling.
> Types of logistic regression: medium. 8 answers: 2 mastered, 3 partial, 3 struggling.
> Binary classification threshold: medium. 8 answers: 3 mastered, 2 partial, 3 struggling.
> Interpreting odds ratios: medium. 8 answers: 4 mastered, 1 partial, 3 struggling.

Student 1 (plain facts):

> Binary classification threshold: mastered. 1 question.
> Interpreting odds ratios: mastered. 1 question.
> Logistic regression and machine learning: mastered. 1 question.
> Types of logistic regression: mastered. 1 question.
> What is logistic regression: mastered. 1 question.

Student 2 (plain facts):

> Interpreting odds ratios: mastered. 1 question.
> Binary classification threshold: partial. 1 question. Review slide 3.
> Logistic regression and machine learning: partial. 1 question. Review slide 6.
> Types of logistic regression: partial. 1 question. Review slide 5.
> What is logistic regression: partial. 1 question. Review slide 2.
