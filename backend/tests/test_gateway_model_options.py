"""The AI code's model options reach the model through the real gateway
(review of #148). The marker, the option verifier and the summaries ask with
temperature 0, a seed and a JSON schema; the production pipeline hands them
`get_ai_gateway().chat_client(...)`, so these tests use the real AiGateway
and its chat_client adapter, with only the model underneath faked."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence

import pytest

from app.schemas.session import ComprehensionLabel
from app.services.ai_gateway import AiGateway, AiLimits, AiRequest, Message
from app.services.free_text_classifier import SAMPLING, FreeTextClassifier
from app.services.generation import VERIFIER_SAMPLING, QuestionGenerator
from app.services.session_summary import LecturerSummariser

from .test_free_text_classifier import QUESTION, C, FakeEmbed, marking
from .test_generation import chunks, draft
from .test_generation_verification import drafts_reply
from .test_session_summary import LOGIT_GOOD, ODDS_GOOD, reply, two_topics

QUICK = AiLimits(max_attempts=1, retry_pause=0.0, keep_warm_interval=0.0)


class RecordingModel:
    """A ModelClient that replies with each of `replies` in turn and keeps the
    options every call was made with."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.options: list[dict] = []

    async def complete(
        self,
        model: str,
        messages: Sequence[Message],
        *,
        max_tokens: int | None,
        options: object = None,
    ) -> str:
        self.options.append(dict(options or {}))
        return self.replies.pop(0)

    async def stream(
        self,
        model: str,
        messages: Sequence[Message],
        *,
        max_tokens: int | None,
        options: object = None,
    ) -> AsyncIterator[str]:
        self.options.append(dict(options or {}))
        yield self.replies.pop(0)

    async def embed(self, model: str, texts: Sequence[str]) -> list[list[float]]:
        raise AssertionError("not used")


def gateway_client(model: RecordingModel, purpose: str):
    return AiGateway(model, "m", QUICK).chat_client(purpose)


async def test_the_marker_asks_at_temperature_0_with_its_schema_through_the_gateway():
    model = RecordingModel(json.dumps(marking(C, C, C)))
    marker = FreeTextClassifier(gateway_client(model, "classification"), FakeEmbed(), "m")
    result = await marker.classify(QUESTION, "full answer")
    assert result.model == "m"
    assert result.label == ComprehensionLabel.MASTERED
    (sent,) = model.options
    assert {k: sent[k] for k in SAMPLING} == SAMPLING
    assert sent["response_format"]["type"] == "json_schema"


async def test_the_marker_without_structured_output_still_sends_its_sampling():
    model = RecordingModel(json.dumps(marking(C, C, C)))
    marker = FreeTextClassifier(
        gateway_client(model, "classification"), FakeEmbed(), "m", structured_output=False
    )
    await marker.classify(QUESTION, "full answer")
    assert model.options == [SAMPLING]


async def test_the_verifier_runs_through_the_gateway_with_its_sampling():
    model = RecordingModel(drafts_reply(draft()), '{"correct": ["B"]}')
    generator = QuestionGenerator(gateway_client(model, "question_generation"), "m", verify=True)
    outcome = await generator._draft(chunks(), 1)
    # The verifier was asked, and its answer rejected the draft: the call
    # was not lost to an adapter that refused its options.
    assert outcome.accepted == []
    assert model.options[1] == VERIFIER_SAMPLING


async def test_the_summary_runs_through_the_gateway_with_its_schema():
    model = RecordingModel(reply(Odds_ratios=ODDS_GOOD, Logit=LOGIT_GOOD))
    summary = await LecturerSummariser(gateway_client(model, "session_summary"), "m").summarise(
        two_topics()
    )
    assert summary.source == "model"
    assert model.options[0]["temperature"] == 0
    assert model.options[0]["response_format"]["type"] == "json_schema"


def test_an_unknown_option_is_refused_rather_than_dropped():
    with pytest.raises(TypeError, match="temprature"):
        AiRequest(messages=(), purpose="test", options={"temprature": 0})
