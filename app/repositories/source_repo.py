"""
Source repository for database access operations.

Provides reusable query functions for Source model using SQLAlchemy ORM.
Handles all source-related CRUD operations while keeping business logic
separated in the service layer.

Functions in this repository:
- Query operations return None if source not found (no exceptions)
- Create/update/delete operations perform db.commit()
- Services/routes are responsible for validation and error handling
"""

from typing import Optional, List
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime

from app.models.source import Source
from app.models.source_index import SourceIndex
from app.models.chat_session import ChatSession


def get_source_by_id(db: Session, source_id: UUID) -> Optional[Source]:
    """
    Get a source by ID.

    Args:
        db: SQLAlchemy database session
        source_id: The source's UUID

    Returns:
        Source object if found, None otherwise
    """
    return db.query(Source).filter(Source.id == source_id).first()


def get_sources_by_user(db: Session, user_id: UUID, skip: int = 0, limit: int = 10) -> tuple[List[Source], int]:
    """
    Get all sources for a user with pagination.

    Args:
        db: SQLAlchemy database session
        user_id: The user's UUID
        skip: Number of records to skip
        limit: Maximum records to return

    Returns:
        Tuple of (sources list, total count)
    """
    query = db.query(Source).filter(Source.user_id == user_id)
    total = query.count()
    sources = query.order_by(desc(Source.created_at)).offset(skip).limit(limit).all()
    return sources, total


def create_source(db: Session, user_id: UUID, title: str, source_type: str, metadata: Optional[dict] = None) -> Source:
    """
    Create a new source.

    Args:
        db: SQLAlchemy database session
        user_id: The user's UUID
        title: Source title
        source_type: Type of source ("pdf" or "github")
        metadata: Optional metadata dict (e.g., {"url": "...", "branch": "..."})

    Returns:
        The created Source object

    Note:
        This function calls db.commit() and db.refresh()
    """
    source = Source(
        user_id=user_id,
        title=title,
        type=source_type,
        source_metadata=metadata or {}
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def update_source_status(db: Session, source_id: UUID, status: str) -> Optional[Source]:
    """
    Update a source's status.

    Args:
        db: SQLAlchemy database session
        source_id: The source's UUID
        status: New status ("uploaded", "indexing", "indexed", or "failed")

    Returns:
        Updated Source object if found, None otherwise
    """
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        return None
    
    source.status = status
    db.commit()
    db.refresh(source)
    return source


def delete_source(db: Session, source_id: UUID) -> bool:
    """
    Delete a source (cascade deletes source_index and message_sources).

    Args:
        db: SQLAlchemy database session
        source_id: The source's UUID

    Returns:
        True if source was deleted, False if not found
    """
    source = db.query(Source).filter(Source.id == source_id).first()
    if not source:
        return False
    
    db.delete(source)
    db.commit()
    return True


def get_source_index(db: Session, source_id: UUID) -> Optional[SourceIndex]:
    """
    Get the source index metadata for a source.

    Args:
        db: SQLAlchemy database session
        source_id: The source's UUID

    Returns:
        SourceIndex object if found, None otherwise
    """
    return db.query(SourceIndex).filter(SourceIndex.source_id == source_id).first()


def create_source_index(db: Session, source_id: UUID, collection_name: str) -> SourceIndex:
    """
    Create a new source index entry.

    Args:
        db: SQLAlchemy database session
        source_id: The source's UUID
        collection_name: Qdrant collection name for vectors

    Returns:
        The created SourceIndex object

    Note:
        This function calls db.commit() and db.refresh()
    """
    source_index = SourceIndex(
        source_id=source_id,
        collection_name=collection_name,
        vector_indexed=False,
        graph_indexed=False,
    )
    db.add(source_index)
    db.commit()
    db.refresh(source_index)
    return source_index


def set_vector_indexed(db: Session, source_id: UUID, vector_indexed: bool = True) -> Optional[SourceIndex]:
    """Set vector_indexed flag and optional timestamp on SourceIndex."""
    source_index = db.query(SourceIndex).filter(SourceIndex.source_id == source_id).first()
    if not source_index:
        return None

    source_index.vector_indexed = bool(vector_indexed)
    source_index.vector_indexed_at = datetime.utcnow() if vector_indexed else None
    db.commit()
    db.refresh(source_index)
    return source_index


def set_graph_indexed(
    db: Session,
    source_id: UUID,
    graph_indexed: bool = True,
    entity_count: int | None = None,
    relation_count: int | None = None,
    error_message: str | None = None,
) -> Optional[SourceIndex]:
    """Set graph_indexed flag, timestamps, and optional entity/relation counts on SourceIndex."""
    source_index = db.query(SourceIndex).filter(SourceIndex.source_id == source_id).first()
    if not source_index:
        return None

    source_index.graph_indexed = bool(graph_indexed)
    source_index.graph_indexed_at = datetime.utcnow() if graph_indexed else None
    if entity_count is not None:
        try:
            source_index.entity_count = int(entity_count)
        except Exception:
            source_index.entity_count = None
    if relation_count is not None:
        try:
            source_index.relation_count = int(relation_count)
        except Exception:
            source_index.relation_count = None
    # Record error message when graph indexing fails
    if error_message:
        try:
            source_index.error_message = str(error_message)[:500]
        except Exception:
            source_index.error_message = None
    else:
        # Clear previous error message on successful indexing
        if graph_indexed:
            source_index.error_message = None

    db.commit()
    db.refresh(source_index)
    return source_index


def get_sources_by_session(db: Session, session_id: UUID) -> list[Source]:
    session = db.query(ChatSession).filter(ChatSession.id == session_id).first()
    return session.sources if session else []