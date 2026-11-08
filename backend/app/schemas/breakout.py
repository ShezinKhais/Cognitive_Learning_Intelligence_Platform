"""Breakout rooms the lecturer assigns.

Owner: General CS, Phase 6.

Microsoft Graph has no way to create breakout rooms or put people in them,
so C.L.I.P keeps its own plan: the lecturer splits the class here, each
student's panel says which room to go to, and the lecturer opens rooms with
the same names in Teams. Room status then works as it does for a room a
student names themselves.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.events import MAX_ROOM_LABEL_LENGTH


class RoomMember(BaseModel):
    user_id: UUID
    name: str
    connected: bool = Field(description="Has the class open now.")


class PlannedRoom(BaseModel):
    label: str
    students: list[RoomMember]


class RoomPlanOut(BaseModel):
    running: bool = Field(description="The class is running, so rooms can be assigned.")
    rooms: list[PlannedRoom]
    unassigned: list[RoomMember] = Field(description="Students on the course in no room.")


class RoomPlanRoomIn(BaseModel):
    label: str = Field(min_length=1, max_length=MAX_ROOM_LABEL_LENGTH)
    user_ids: list[UUID] = Field(max_length=500)


class RoomPlanIn(BaseModel):
    rooms: list[RoomPlanRoomIn] = Field(default_factory=list, max_length=50)
