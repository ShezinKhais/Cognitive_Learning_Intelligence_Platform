"""Version 1 of the API.

Everything is mounted under /api/v1. A breaking change to any contract in
app.schemas means a v2 router alongside this one, not an edit in place.
"""

from fastapi import APIRouter

from app.api.v1 import content, health, identity, sessions, ws

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(identity.router)
api_router.include_router(content.router)
api_router.include_router(sessions.router)

# Not versioned in the path: the socket carries its own protocol version in the
# auth handshake, so upgrading it does not require a new URL.
ws_router = ws.router
