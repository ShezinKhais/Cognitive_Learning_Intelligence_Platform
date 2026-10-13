"""Perplexity of lecture text under a language model.

Owner: AI 1, Phase 8 (#73). Perplexity is how surprised a model is by text,
on average per token: exp of the mean negative log-likelihood. Lower means
the model finds the text more predictable, which suggests it knows the
subject's language better. It says nothing directly about whether questions
or marks are good; the task metrics in tests/eval do that.

Pure arithmetic, so it needs no model; scripts/perplexity.py computes the
log-likelihoods with Hugging Face transformers, since Ollama does not return
them for text it is given.
"""

from __future__ import annotations

import math
from collections.abc import Iterable


def perplexity(scored: Iterable[tuple[float, int]]) -> float:
    """Perplexity over several texts from (summed negative log-likelihood in
    nats, tokens scored) per text.

    The texts are pooled by token, not averaged per text, so a long chunk
    counts more than a short one, as it would if the texts were one.
    """
    total_nll = total_tokens = 0
    for nll, tokens in scored:
        if tokens < 0 or nll < 0:
            raise ValueError("negative log-likelihood and token counts must not be negative")
        total_nll += nll
        total_tokens += tokens
    if total_tokens == 0:
        raise ValueError("no tokens were scored")
    return math.exp(total_nll / total_tokens)
