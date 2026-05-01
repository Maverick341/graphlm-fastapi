from uuid import uuid4
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, String, Integer
from sqlalchemy.sql import func
from datetime import datetime
from app.db.database import Base

class SourceIndex(Base):
    __tablename__ = "source_indexes"

    id:        Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Vector (Qdrant)
    collection_name:  Mapped[str]            = mapped_column(String, nullable=False)
    vector_indexed:   Mapped[bool]           = mapped_column(default=False)
    vector_indexed_at: Mapped[datetime|None] = mapped_column(nullable=True)

    # Graph (Neo4j)
    graph_indexed:    Mapped[bool]           = mapped_column(default=False)
    graph_indexed_at: Mapped[datetime|None]  = mapped_column(nullable=True)
    entity_count:     Mapped[int|None]       = mapped_column(Integer, nullable=True)
    relation_count:   Mapped[int|None]       = mapped_column(Integer, nullable=True)

    error_message: Mapped[str | None] = mapped_column(String, nullable=True)

    # Indexing logic (placeholder, implement in service layer)
    # try:
    #     # indexing logic
    #     pass
    # except Exception as e:
    #     source_index.error_message = str(e)[:500]
    #     source.status = "failed"
    #     db.commit()

    # Shared config
    provider:        Mapped[str]      = mapped_column(String, default="qdrant+neo4j")
    embedding_model: Mapped[str]      = mapped_column(String, default="text-embedding-3-small")
    chunk_size:      Mapped[int]      = mapped_column(Integer, default=1000)
    chunk_overlap:   Mapped[int]      = mapped_column(Integer, default=200)

    source: Mapped["Source"] = relationship("Source", back_populates="source_index")