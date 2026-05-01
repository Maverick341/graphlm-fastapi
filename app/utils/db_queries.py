"""
Utility functions for generic validation and response building.

Provides reusable helpers for ownership verification and schema building.
Database access operations have moved to repositories (session_repo, source_repo).
"""

from uuid import UUID

from app.models.source import Source
from app.schemas.source import SourceStatusResponse, SourceIndexStatus
from app.utils.api_error import ApiError


# ─────────────────────────────────────────────────────────────────────────
# Generic Ownership Verification
# ─────────────────────────────────────────────────────────────────────────

def verify_ownership(resource_user_id: UUID, current_user_id: UUID, resource_type: str = "resource") -> None:
    """
    Verify that a resource belongs to the current user.
    
    Raises 403 if resource does not belong to user.
    
    Args:
        resource_user_id: User ID from the resource (e.g., session.user_id)
        current_user_id: ID of the current authenticated user
        resource_type: Type of resource for error message (e.g., "session", "source")
    
    Raises:
        ApiError(403): If ownership verification fails
    """
    if resource_user_id != current_user_id:
        raise ApiError(403, f"This {resource_type} does not belong to you")


def build_source_status_response(source: Source) -> SourceStatusResponse:
    """
    Build SourceStatusResponse from Source and SourceIndex.
    
    Shows detailed indexing status for vector and graph pipelines.
    
    Args:
        source: Source model instance
    
    Returns:
        SourceStatusResponse with current indexing status
    """
    source_index = source.source_index
    
    # Vector indexing status
    vector_status = SourceIndexStatus(
        indexed=source_index.vector_indexed if source_index else False,
        indexed_at=source_index.vector_indexed_at if source_index else None,
    )
    
    # Graph indexing status
    graph_status = SourceIndexStatus(
        indexed=source_index.graph_indexed if source_index else False,
        indexed_at=source_index.graph_indexed_at if source_index else None,
        entity_count=source_index.entity_count if source_index else None,
        relation_count=source_index.relation_count if source_index else None,
    )
    
    return SourceStatusResponse(
        source_id=source.id,
        title=source.title,
        type=source.type.value,
        overall_status=source.status.value,
        vector=vector_status,
        graph=graph_status,
        collection_name=source_index.collection_name if source_index else None,
        error_message=source_index.error_message if source_index else None,
    )
