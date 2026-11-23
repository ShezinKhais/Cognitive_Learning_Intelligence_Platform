"""Perplexity of lecture text under a language model.

Owner: AI 1, Phase 8 (#73). Perplexity is how surprised a model is by text,
on average per token: exp of the mean negative log-likelihood. Lower means
the model finds the text more predictable, which suggests it knows the
subject's language better. It says nothing directly about whether questions
or marks are good; the task metrics in tests/eval do that.

Perplexity is per token, and every model family cuts text into tokens
differently, so it compares models that share a tokenizer (Qwen2.5 0.5B and
1.5B) but not across families (Qwen against Gemma). Bits per byte divides the
same log-likelihood by the length of the text in UTF-8 bytes instead, which
is the same whatever the tokenizer, so it compares any two models.

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


def bits_per_byte(scored: Iterable[tuple[float, int]]) -> float:
    """Bits per byte over several texts from (summed negative log-likelihood
    in nats, UTF-8 bytes of text) per text, pooled by byte. Lower is better."""
    total_nll = total_bytes = 0
    for nll, size in scored:
        if size < 0 or nll < 0:
            raise ValueError("negative log-likelihood and byte counts must not be negative")
        total_nll += nll
        total_bytes += size
    if total_bytes == 0:
        raise ValueError("no text was scored")
    return total_nll / (total_bytes * math.log(2))
