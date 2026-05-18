"""
Session schemas for chat sessions, messages, and knowledge graph queries.

Includes request validation schemas and response schemas following the ApiResponse pattern.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
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

    When subgraph_mode is True, the agent will call the subgraph_query tool
    alongside its normal response and emit a graph_update SSE event with
    relevant nodes and edges for the graph panel visualization.

    selected_source_ids controls which sources the subgraph_query tool is scoped
    to when subgraph_mode is True. Has no effect on standalone chat (subgraph_mode=False),
    which always uses all session sources.
    """
    content: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="User message content"
    )
    subgraph_mode: bool = Field(
        default=False,
        description=(
            "When True, agent calls subgraph_query tool and emits "
            "a graph_update SSE event for the KG panel."
        ),
    )
    selected_source_ids: Optional[List[str]] = Field(
        default=None,
        description=(
            "Source IDs to scope the subgraph_query tool to when subgraph_mode=True. "
            "Must be a subset of sources attached to the session. "
            "Ignored when subgraph_mode=False. "
            "Defaults to all graph-indexed session sources when omitted."
        ),
    )

    class Config:
        json_schema_extra = {
            "example": {
                "content": "What are the main features of this system?",
                "subgraph_mode": True,
                "selected_source_ids": ["323e4567-e89b-12d3-a456-426614174002"],
            }
        }


class GraphQueryRequest(BaseModel):
    """
    Standalone knowledge graph explore query.

    Used by the KG Studio panel's Explore tab — independent of chat.
    Query is scoped to sources attached to the session.
    Results are controlled by max_nodes and hop_depth.

    If source_ids is provided, the query is scoped to those sources only
    (must be a subset of the session's attached sources).
    If omitted, all session sources are used.
    """
    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Natural language description of the subgraph to explore",
    )
    max_nodes: int = Field(
        default=200,
        ge=10,
        le=500,
        description="Maximum number of nodes to return (10–500, default 200)",
    )
    hop_depth: int = Field(
        default=2,
        ge=1,
        le=3,
        description=(
            "Relationship traversal depth: "
            "1 = direct neighbours only, "
            "2 = neighbours of neighbours (default), "
            "3 = three hops (wide, may be slow)"
        ),
    )
    source_ids: Optional[List[str]] = Field(
        default=None,
        description=(
            "Optional subset of source IDs to scope the query to. "
            "Must be IDs of sources attached to this session. "
            "Defaults to all session sources when omitted or null."
        ),
    )

    class Config:
        json_schema_extra = {
            "example": {
                "query": "authentication flow and JWT token handling",
                "max_nodes": 150,
                "hop_depth": 2,
                "source_ids": ["323e4567-e89b-12d3-a456-426614174002"],
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
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific metadata",
        validation_alias="source_metadata"
    )
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
    source_ids: Optional[List[UUID]] = Field(
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
                "source_count": 1,
                "source_ids": [
                    "323e4567-e89b-12d3-a456-426614174002"
                ]
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
    properties: Dict[str, Any] = Field(
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
    properties: Dict[str, Any] = Field(
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


# ─────────────────────────────────────────────────────────────────────────
# CONTEXT INFRASTRUCTURE SCHEMAS
# ─────────────────────────────────────────────────────────────────────────

class ContextStateResponse(BaseModel):
    """
    Session context state for debug/observability.

    Returned by GET /sessions/{id}/context/state
    """
    session_id: str = Field(description="Session ID")
    estimated_token_usage: int = Field(description="Current estimated token usage")
    available_budget: int = Field(description="Available token budget")
    usage_percent: float = Field(description="Current usage as percentage of budget")
    compaction_threshold: float = Field(description="Compaction trigger threshold (ratio)")
    needs_compaction: bool = Field(description="Whether compaction is pending")
    has_summary: bool = Field(description="Whether a rolling summary exists")
    recent_window_size: int = Field(description="Recent message window size")
    last_compacted_at: Optional[str] = Field(default=None, description="Last compaction timestamp")
    last_compacted_message_id: Optional[str] = Field(default=None, description="Last compacted message boundary")


class CompactionEvaluationResponse(BaseModel):
    """
    Result of compaction evaluation.

    Returned by POST /sessions/{id}/context/evaluate
    """
    session_id: str = Field(description="Session ID")
    estimated_tokens: int = Field(description="Estimated total tokens")
    available_budget: int = Field(description="Available token budget")
    usage_ratio: float = Field(description="Usage as ratio of budget (0.0-1.0)")
    threshold: float = Field(description="Compaction threshold")
    needs_compaction: bool = Field(description="Whether compaction is needed")
    recent_message_count: int = Field(description="Number of recent messages")
    summary_tokens: int = Field(description="Tokens used by rolling summary")
    recent_tokens: int = Field(description="Tokens used by recent messages")


class CompactionResultResponse(BaseModel):
    """
    Result of compaction operation.

    Returned by POST /sessions/{id}/context/compact
    """
    session_id: str = Field(description="Session ID")
    compacted: bool = Field(description="Whether compaction was performed")
    reason: Optional[str] = Field(default=None, description="Reason if not compacted")
    messages_compacted: Optional[int] = Field(default=None, description="Number of messages compacted")
    summary_tokens: Optional[int] = Field(default=None, description="Summary token count after compaction")
    recent_tokens: Optional[int] = Field(default=None, description="Recent message tokens after compaction")
    total_tokens: Optional[int] = Field(default=None, description="Total tokens after compaction")
    available_budget: Optional[int] = Field(default=None, description="Available budget")
    headroom: Optional[int] = Field(default=None, description="Remaining headroom tokens")


class ContextSummaryResponse(BaseModel):
    """
    Rolling summary and metadata.

    Returned by GET /sessions/{id}/context/summary
    """
    session_id: str = Field(description="Session ID")
    rolling_summary: Optional[str] = Field(default=None, description="Rolling summary text")
    summary_tokens: int = Field(description="Token count of the summary")
    last_compacted_at: Optional[str] = Field(default=None, description="Last compaction timestamp")
    last_compacted_message_id: Optional[str] = Field(default=None, description="Last compacted message boundary")


class ContextRebuildResponse(BaseModel):
    """
    Result of context rebuild (recovery/admin).

    Returned by POST /sessions/{id}/context/rebuild
    """
    session_id: str = Field(description="Session ID")
    rebuilt: bool = Field(description="Whether rebuild was performed")
    total_messages: int = Field(description="Total messages in transcript")
    estimated_tokens: int = Field(description="Estimated tokens after rebuild")
    needs_compaction: bool = Field(description="Whether compaction is now needed")
    summary_cleared: bool = Field(description="Whether previous summary was cleared")

