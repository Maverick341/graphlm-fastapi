"""
Session schemas for chat sessions, messages, and knowledge graph queries.

Includes request validation schemas and response schemas following the ApiResponse pattern.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any
from uuid import UUID
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────
# REQUEST SCHEMAS (Input validation)
# ─────────────────────────────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    """
    Create new chat session request.
    
    Title is optional and defaults to "Untitled" if omitted or empty.
    """
    title: Optional[str] = Field(
        default="Untitled",
        min_length=1,
        max_length=200,
        description="Session title (optional, defaults to 'Untitled')"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "title": "GraphLM Query Session"
            }
        }


class RenameTitleRequest(BaseModel):
    """
    Rename chat session title.
    
    Title is required and non-empty.
    """
    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="New session title"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "title": "Updated Session Title"
            }
        }


class AttachSourcesRequest(BaseModel):
    """
    Attach sources to chat session.
    
    Only allowed if session has zero messages.
    All source IDs must exist and belong to current user.
    """
    source_ids: List[UUID] = Field(
        ...,
        min_length=1,
        description="List of source IDs to attach to session"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "source_ids": [
                    "123e4567-e89b-12d3-a456-426614174000",
                    "223e4567-e89b-12d3-a456-426614174001"
                ]
            }
        }


class SendMessageRequest(BaseModel):
    """
    Send message in chat session.
    
    Triggers RAG pipeline with vector + graph retrieval.
    Message is persisted immediately; streaming response follows.
    """
    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="User message content"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "content": "What are the main features of this system?"
            }
        }


class GraphQueryRequest(BaseModel):
    """
    Query knowledge graph for subgraph extraction.
    
    Used by KG Studio panel for interactive visualization.
    Query is scoped to sources attached to session.
    """
    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Natural language search query for knowledge graph"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "query": "authentication mechanisms"
            }
        }


# ─────────────────────────────────────────────────────────────────────────
# RESPONSE SCHEMAS (Output serialization)
# ─────────────────────────────────────────────────────────────────────────

class SourceSummaryResponse(BaseModel):
    """
    Minimal source information for session context.
    
    Used when listing sessions with attached sources.
    """
    id: UUID = Field(description="Source ID")
    title: str = Field(description="Source title")
    type: str = Field(description="Source type: 'pdf' or 'github'")
    status: str = Field(description="Indexing status: 'uploaded', 'indexing', 'indexed', or 'failed'")
    created_at: datetime = Field(description="Source creation timestamp")

    class Config:
        from_attributes = True


class SessionResponse(BaseModel):
    """
    Chat session response with metadata and attached sources.
    
    Returned by session CRUD endpoints.
    """
    id: UUID = Field(description="Session ID")
    user_id: UUID = Field(description="Owner user ID")
    title: str = Field(description="Session title")
    created_at: datetime = Field(description="Session creation timestamp")
    sources: List[SourceSummaryResponse] = Field(
        default_factory=list,
        description="Attached sources for this session"
    )
    message_count: Optional[int] = Field(
        default=None,
        description="Total number of messages in session (optional)"
    )
    source_count: Optional[int] = Field(
        default=None,
        description="Total number of sources attached to session (optional)"
    )
    sources: Optional[List[UUID]] = Field(
        default=None,
        description="List of attached source IDs (optional)"
    )

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "user_id": "223e4567-e89b-12d3-a456-426614174001",
                "title": "GraphLM Query Session",
                "created_at": "2026-04-30T10:30:00Z",
                "sources": [
                    {
                        "id": "323e4567-e89b-12d3-a456-426614174002",
                        "title": "architecture.pdf",
                        "type": "pdf",
                        "status": "indexed",
                        "created_at": "2026-04-30T10:25:00Z"
                    }
                ],
                "message_count": 5,
                "source_count": 1
            }
        }


class MessageResponse(BaseModel):
    """
    Single chat message in session.
    
    Role indicates sender type (user or assistant).
    """
    id: UUID = Field(description="Message ID")
    chat_id: UUID = Field(description="Parent session ID")
    role: str = Field(
        description="Sender role: 'user' or 'assistant'",
        pattern="^(user|assistant)$"
    )
    content: str = Field(description="Message content")
    created_at: datetime = Field(description="Message creation timestamp")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "423e4567-e89b-12d3-a456-426614174003",
                "chat_id": "123e4567-e89b-12d3-a456-426614174000",
                "role": "user",
                "content": "What are the main features?",
                "created_at": "2026-04-30T10:35:00Z"
            }
        }


class PaginationInfo(BaseModel):
    """
    Pagination metadata for list endpoints.
    """
    skip: int = Field(description="Number of items skipped")
    limit: int = Field(description="Maximum items per page")
    total: int = Field(description="Total items available")
    has_more: bool = Field(description="Whether more items exist beyond this page")


class PaginatedMessagesResponse(BaseModel):
    """
    Paginated messages response for session message history.
    
    Includes pagination metadata for client-side navigation.
    """
    messages: List[MessageResponse] = Field(description="Messages for current page")
    pagination: PaginationInfo = Field(description="Pagination metadata")

    class Config:
        json_schema_extra = {
            "example": {
                "messages": [
                    {
                        "id": "423e4567-e89b-12d3-a456-426614174003",
                        "chat_id": "123e4567-e89b-12d3-a456-426614174000",
                        "role": "user",
                        "content": "What are the main features?",
                        "created_at": "2026-04-30T10:35:00Z"
                    },
                    {
                        "id": "523e4567-e89b-12d3-a456-426614174004",
                        "chat_id": "123e4567-e89b-12d3-a456-426614174000",
                        "role": "assistant",
                        "content": "The system includes...",
                        "created_at": "2026-04-30T10:35:05Z"
                    }
                ],
                "pagination": {
                    "skip": 0,
                    "limit": 50,
                    "total": 12,
                    "has_more": False
                }
            }
        }


class GraphNode(BaseModel):
    """
    Knowledge graph node (entity).
    """
    id: str = Field(description="Node ID")
    label: str = Field(description="Node display label")
    properties: dict = Field(
        default_factory=dict,
        description="Node properties (e.g., name, type, description)"
    )


class GraphEdge(BaseModel):
    """
    Knowledge graph edge (relationship).
    """
    source: str = Field(description="Source node ID")
    target: str = Field(description="Target node ID")
    relationship_type: str = Field(description="Relationship type/label")
    properties: dict = Field(
        default_factory=dict,
        description="Edge properties (e.g., weight, metadata)"
    )


class GraphResponse(BaseModel):
    """
    Knowledge graph query result (subgraph).
    
    Returned by /graph/query endpoint for visualization.
    Used by KG Studio panel.
    """
    nodes: List[GraphNode] = Field(description="Graph nodes (entities)")
    edges: List[GraphEdge] = Field(description="Graph edges (relationships)")
    anchor_ids: List[str] = Field(
        default_factory=list,
        description="Highlighted/anchor node IDs for visualization focus"
    )
    query: Optional[str] = Field(
        default=None,
        description="Echoed query for reference"
    )
    truncated: bool = Field(
        default=False,
        description="Whether result was truncated (max 500 nodes)"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "nodes": [
                    {
                        "id": "auth_001",
                        "label": "Authentication",
                        "properties": {"type": "concept", "description": "User authentication mechanism"}
                    },
                    {
                        "id": "jwt_001",
                        "label": "JWT",
                        "properties": {"type": "technology", "name": "JSON Web Token"}
                    }
                ],
                "edges": [
                    {
                        "source": "auth_001",
                        "target": "jwt_001",
                        "relationship_type": "USES",
                        "properties": {"weight": 1.0}
                    }
                ],
                "anchor_ids": ["auth_001"],
                "query": "authentication",
                "truncated": False
            }
        }


class FullGraphResponse(BaseModel):
    """
    Full knowledge graph for session (all entities and relationships).
    
    Returned by /graph endpoint. Capped at 500 nodes.
    """
    nodes: List[GraphNode] = Field(description="All graph nodes")
    edges: List[GraphEdge] = Field(description="All graph edges")
    truncated: bool = Field(
        default=False,
        description="True if result exceeded 500 nodes"
    )
    node_count: int = Field(description="Total nodes in result")
    edge_count: int = Field(description="Total edges in result")
