"""The bot's chat replies. Outbound posts are faked."""

from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.config import Settings
from app.schemas.meetings import TeamsActivity
from app.services import teams_replies
from app.services.teams_replies import HELP, WELCOME, answer, command_of, reply_text


def activity(**fields) -> TeamsActivity:
    return TeamsActivity(
        serviceUrl="https://smba.trafficmanager.net/emea/", channelId="msteams", **fields
    )


@pytest.mark.parametrize(
    ("text", "word"),
    [
        ("<at>C.L.I.P</at> status", "status"),
        ("  STATUS please", "status"),
        ("<p><at>C.L.I.P</at> help</p>", "help"),
        ("", ""),
        (None, ""),
    ],
)
def test_the_command_is_the_first_word_after_the_mention(text, word) -> None:
    assert command_of(text) == word


async def test_anything_but_status_gets_the_help_text() -> None:
    assert await reply_text(AsyncMock(), activity(type="message", text="hello")) == HELP


async def test_status_names_the_meeting_session(monkeypatch) -> None:
    seen = {}

    async def status(_db, meeting_id):
        seen["meeting"] = meeting_id
        return "running"

    monkeypatch.setattr(teams_replies, "status_text", status)
    message = activity(
        type="message", text="<at>C.L.I.P</at> status", channelData={"meeting": {"id": "m1"}}
    )
    assert await reply_text(AsyncMock(), message) == "running"
    assert seen["meeting"] == "m1"


async def test_status_outside_a_meeting_says_where_to_ask() -> None:
    text = await teams_replies.status_text(AsyncMock(), None)
    assert "chat" in text


async def test_the_bot_greets_a_chat_only_when_it_is_the_one_added() -> None:
    added = activity(
        type="conversationUpdate", recipient={"id": "28:bot"}, membersAdded=[{"id": "28:bot"}]
    )
    someone = activity(
        type="conversationUpdate", recipient={"id": "28:bot"}, membersAdded=[{"id": "29:x"}]
    )
    start = activity(type="event", name="application/vnd.microsoft.meetingStart")
    assert await reply_text(AsyncMock(), added) == WELCOME
    assert await reply_text(AsyncMock(), someone) is None
    assert await reply_text(AsyncMock(), start) is None


async def test_a_failed_reply_is_logged_and_never_raised(caplog) -> None:
    async def broken(*_):
        raise httpx.ConnectError("down")

    await answer(AsyncMock(), activity(type="message", text="help"), Settings(), post=broken)
    assert "bot reply not sent" in caplog.text


async def test_the_reply_threads_under_the_message(monkeypatch) -> None:
    sent = {}

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, url, headers, json):
            sent.update(url=url, json=json)
            return httpx.Response(201, request=httpx.Request("POST", url))

    async def token(*_):
        return "t"

    monkeypatch.setattr(teams_replies.httpx, "AsyncClient", Client)
    monkeypatch.setattr(teams_replies.notifications, "access_token", token)
    message = activity(type="message", text="help", id="act/1", conversation={"id": "19:chat"})
    await teams_replies.post_reply(Settings(), message, "hi")
    assert sent["url"] == (
        "https://smba.trafficmanager.net/emea/v3/conversations/19%3Achat/activities/act%2F1"
    )
    assert sent["json"] == {"type": "message", "textFormat": "markdown", "text": "hi"}
