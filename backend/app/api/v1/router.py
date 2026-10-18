"""Version 1 of the API.

Everything is mounted under /api/v1. A breaking change to any contract in
app.schemas means a v2 router alongside this one, not an edit in place.
"""

from fastapi import APIRouter

from app.api.v1 import (
    chat,
    consideration,
    content,
    governance,
    health,
    identity,
    meetings,
    my_data,
    reports,
    sessions,
    student_review,
    teams,
    ws,
)

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(identity.router)
api_router.include_router(content.router)
api_router.include_router(sessions.router)
api_router.include_router(student_review.router)
api_router.include_router(my_data.router)
api_router.include_router(reports.router)
api_router.include_router(chat.router)
api_router.include_router(consideration.router)
api_router.include_router(meetings.router)
api_router.include_router(teams.router)
api_router.include_router(governance.router)

# Not versioned in the path: the socket carries its own protocol version in the
# auth handshake, so upgrading it does not require a new URL.
ws_router = ws.router
