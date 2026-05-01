from sqlalchemy import Table, Column, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from app.db.database import Base

chat_session_sources = Table(
    "chat_session_sources",
    Base.metadata,
    Column(
        "session_id",
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "source_id",
        UUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)