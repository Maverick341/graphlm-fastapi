from uuid import uuid4
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, String, Enum, JSON
from sqlalchemy.sql import func
from datetime import datetime
import enum
from app.db.database import Base

class SourceType(enum.Enum):
    pdf        = "pdf"
    github     = "github"

class SourceStatus(enum.Enum):
    uploaded  = "uploaded"
    indexing  = "indexing"
    indexed   = "indexed"
    failed    = "failed"

class Source(Base):
    __tablename__ = "sources"

    id:         Mapped[UUID]         = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4, index=True)
    user_id:    Mapped[UUID]         = mapped_column(ForeignKey("users.id",         ondelete="CASCADE"), nullable=False)
    session_id: Mapped[UUID]         = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False)
    title:      Mapped[str]          = mapped_column(String, nullable=False)
    type:       Mapped[SourceType]   = mapped_column(Enum(SourceType),   nullable=False)
    status:     Mapped[SourceStatus] = mapped_column(Enum(SourceStatus), default=SourceStatus.uploaded)
    source_metadata: Mapped[dict]        = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime]     = mapped_column(default=func.now())

    source_index: Mapped["SourceIndex"] = relationship(
        "SourceIndex",
        back_populates="source",
        cascade="all, delete-orphan",
        uselist=False
    )