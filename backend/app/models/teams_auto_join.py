"""How far the calendar sweep got in putting C.L.I.P into a class meeting.

Owner: General CS, Phase 8. One row per meeting chat the sweep installed
C.L.I.P into, written before the tab is pinned so a backend restart picks up
where it stopped. Once the tab is pinned the row marks the meeting done, and
the sweep never touches that meeting again, so a lecturer who removes C.L.I.P
from it keeps it removed. Holds no meeting content, only the chat's id.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TeamsAutoJoin(Base):
    __tablename__ = "teams_auto_join"

    chat_thread: Mapped[str] = mapped_column(String(512), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(256), nullable=False)
    tab_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Set when this sweep's install was the one that added C.L.I.P, and
    # cleared once the lecturer has been sent the notice.
    notice_owed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
