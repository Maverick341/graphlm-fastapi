"""
Session utility functions for consistent validation and response building.
Consolidates repeated session verification and response construction patterns.
"""

from uuid import UUID
from sqlalchemy.orm import Session
from app.models.user import User
from app.models.chat_session import ChatSession
from app.schemas.session import SessionResponse
from app.repositories import session_repo
from app.utils.db_queries import verify_ownership
from app.utils.api_error import ApiError


async def get_session_with_auth(
    db: Session,
    session_id: UUID,
    current_user: User,
) -> ChatSession:
    """
    Get a session and verify ownership.
    
    Args:
        db: Database session
        session_id: Session ID to retrieve
        current_user: Authenticated user (for ownership check)
    
    Returns:
        ChatSession ORM object
    
    Raises:
        ApiError(404): If session not found
        ApiError(403): If session doesn't belong to user
    """
    session = session_repo.get_session_by_id(db, session_id)
    if not session:
        raise ApiError(404, "Session not found")
    
    verify_ownership(session.user_id, current_user.id, "session")
    return session


def build_session_response(db: Session, session: ChatSession) -> SessionResponse:
    """
    Build a complete SessionResponse with counts and metadata.
    
    Args:
        db: Database session
        session: ChatSession ORM object
    
    Returns:
        SessionResponse with message_count, source_count, source_ids populated
    """
    response = SessionResponse.model_validate(session)
    response.message_count = session_repo.get_message_count(db, session.id)
    response.source_count = len(session.sources)
    response.source_ids = [s.id for s in session.sources]
    return response


def build_session_list_response(db: Session, sessions: list[ChatSession]) -> list[SessionResponse]:
    """
    Build SessionResponse objects for a list of sessions.
    
    Args:
        db: Database session
        sessions: List of ChatSession ORM objects
    
    Returns:
        List of SessionResponse with counts populated
    """
    return [build_session_response(db, session) for session in sessions]
