from uuid import uuid4

import httpx
import pytest

from app.services.meeting_organiser import lookup_short_meeting, short_meeting_id

THREAD = "19:meeting_example@thread.v2"
MEETING_NUMBER = "123456789012"


def test_only_the_teams_meeting_number_is_read():
    assert short_meeting_id(f"https://teams.microsoft.com/meet/{MEETING_NUMBER}?p=secret") == (
        MEETING_NUMBER
    )
    for url in (
        "https://teams.microsoft.com.evil.example/meet/123456789012",
        "https://teams.microsoft.com/meet/123456789012/extra",
        "https://teams.microsoft.com/meet/123456789012abc",
        "https://teams.live.com/meet/123456789012",
    ):
        assert short_meeting_id(url) is None


@pytest.mark.parametrize("case", ["organiser", "attendee", "multiple", "denied", "full_link"])
async def test_short_link_lookup_checks_the_organiser_and_never_sends_the_passcode(case):
    organiser = str(uuid4())

    def graph(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "graph.microsoft.com"
        assert request.url.path == f"/v1.0/users/{organiser}/onlineMeetings"
        assert dict(request.url.params) == {
            "$filter": f"joinMeetingIdSettings/joinMeetingId eq '{MEETING_NUMBER}'"
        }
        if case == "denied":
            return httpx.Response(403)
        meeting = {
            "participants": {
                "organizer": {
                    "identity": {"user": {"id": str(uuid4()) if case == "attendee" else organiser}}
                }
            },
        }
        if case == "full_link":
            meeting["joinWebUrl"] = (
                "https://teams.microsoft.com/l/meetup-join/19%3Ameeting_example%40thread.v2/0"
            )
        else:
            meeting["chatInfo"] = {"threadId": THREAD}
        return httpx.Response(
            200, json={"value": [meeting, meeting] if case == "multiple" else [meeting]}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(graph)) as client:
        thread = await lookup_short_meeting(client, {}, organiser, MEETING_NUMBER)
    assert thread == (THREAD if case in ("organiser", "full_link") else None)
