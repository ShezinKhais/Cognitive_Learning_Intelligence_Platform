"""Regression coverage for documented Teams lifecycle payloads, without a tenant."""

from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.schemas.meetings import TeamsActivity, activity_meeting_id
from app.services.teams_bot import meeting_event
from app.services.teams_notifications import remember_reference

START = "application/vnd.microsoft.meetingStart"
END = "application/vnd.microsoft.meetingEnd"


def activity(**changes):
    return TeamsActivity.model_validate(
        {
            "type": "event",
            "name": START,
            "serviceUrl": "https://smba.trafficmanager.net/teams/",
            "channelId": "msteams",
            "conversation": {"id": "meeting-chat"},
            "channelData": {"tenant": {"id": "tenant"}},
            "value": {"Id": "meeting-id", "MeetingType": "Scheduled", "Title": "Lecture"},
            **changes,
        }
    )


def configured():
    return Settings(
        client_id="bot",
        client_secret="test-secret",
        tenant_id="tenant",
        teams_notifications_enabled=True,
        teams_app_base_url="https://clip.example",
        teams_app_id="00000000-0000-0000-0000-000000000051",
    )


@pytest.mark.parametrize(("name", "kind"), [(START, "started"), (END, "ended")])
async def test_documented_value_id_is_used_for_both_lifecycle_and_reference(name, kind):
    incoming = activity(name=name)
    parsed = meeting_event(incoming)
    assert (parsed.kind, parsed.meeting_id) == (kind, "meeting-id")
    db = AsyncMock()
    settings = configured()
    await remember_reference(db, incoming, settings)
    db.execute.assert_awaited_once()
    statement = db.execute.await_args.args[0].compile().params
    assert statement["meeting_id"] == "meeting-id"
    assert statement["conversation_id"] == "meeting-chat"
    db.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "value", [None, [], "meeting-id", {}, {"Id": 123}, {"Id": ""}, {"Id": " "}, {"Id": "m" * 257}]
)
def test_malformed_lifecycle_value_cannot_identify_a_meeting(value):
    assert activity_meeting_id(activity(value=value)) is None
    assert meeting_event(activity(value=value)) is None


@pytest.mark.parametrize("kind", ["message", "installationUpdate", "conversationUpdate"])
def test_arbitrary_activity_value_is_not_a_meeting_identity(kind):
    assert activity_meeting_id(activity(type=kind)) is None


async def test_conflicting_identifiers_are_not_saved_or_applied():
    incoming = activity(channelData={"tenant": {"id": "tenant"}, "meeting": {"id": "other"}})
    assert activity_meeting_id(incoming) is None
    assert meeting_event(incoming) is None
    db = AsyncMock()
    await remember_reference(db, incoming, configured())
    db.execute.assert_not_awaited()


def test_matching_identifiers_and_existing_chat_format_are_supported():
    data = {"tenant": {"id": "tenant"}, "meeting": {"id": "meeting-id"}}
    assert activity_meeting_id(activity(channelData=data)) == "meeting-id"
    assert (
        activity_meeting_id(activity(type="message", value=None, channelData=data)) == "meeting-id"
    )
