"""Perplexity arithmetic for the AI evaluation report (Phase 8, AI 1, #73)."""

import math

import pytest

from app.services.perplexity import perplexity


def test_a_model_certain_of_every_token_has_perplexity_one():
    assert perplexity([(0.0, 10)]) == 1.0


def test_perplexity_is_exp_of_mean_negative_log_likelihood():
    # Each token given probability 1/4: NLL ln 4 per token, perplexity 4.
    assert perplexity([(10 * math.log(4), 10)]) == pytest.approx(4.0)


def test_texts_are_pooled_by_token_not_averaged_per_text():
    long = (90 * math.log(2), 90)  # perplexity 2 over 90 tokens
    short = (10 * math.log(8), 10)  # perplexity 8 over 10 tokens
    pooled = math.exp((90 * math.log(2) + 10 * math.log(8)) / 100)
    assert perplexity([long, short]) == pytest.approx(pooled)
    assert perplexity([long, short]) < (2 + 8) / 2


def test_nothing_scored_is_an_error():
    with pytest.raises(ValueError):
        perplexity([(0.0, 0)])


def test_negative_values_are_an_error():
    with pytest.raises(ValueError):
        perplexity([(-1.0, 5)])


def test_bits_per_byte_divides_nats_by_bytes_and_ln2():
    from app.services.perplexity import bits_per_byte

    # One bit (ln 2 nats) per byte over 10 bytes.
    assert bits_per_byte([(10 * math.log(2), 10)]) == pytest.approx(1.0)


def test_bits_per_byte_pools_by_byte():
    from app.services.perplexity import bits_per_byte

    pooled = (2 * math.log(2) + 6 * math.log(2)) / (2 + 2) / math.log(2)
    assert bits_per_byte([(2 * math.log(2), 2), (6 * math.log(2), 2)]) == pytest.approx(pooled)


def test_bits_per_byte_needs_some_text():
    from app.services.perplexity import bits_per_byte

    with pytest.raises(ValueError):
        bits_per_byte([(0.0, 0)])
