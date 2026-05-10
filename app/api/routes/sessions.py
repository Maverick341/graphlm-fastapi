"""
Chat session routes for GraphLM FastAPI backend.

Endpoints for managing chat sessions, messages, and knowledge graph queries.
All endpoints require authentication (current_user).
All endpoints return responses wrapped in ApiResponse.
"""

from fastapi import APIRouter, Depends, Query, Request, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
from typing import Optional

from app.db.database import get_db
from app.models.user import User
from app.models.chat_session import ChatSession
from app.models.chat_message import ChatMessage, MessageRole
from app.models.source import Source
from app.api.deps import get_current_user, get_current_admin
from app.schemas.response import ApiResponse
from app.schemas.session import (
    CreateSessionRequest,
    RenameTitleRequest,
    AttachSourcesRequest,
    SendMessageRequest,
    GraphQueryRequest,
    SessionResponse,
    MessageResponse,
    PaginatedMessagesResponse,
    PaginationInfo,
    GraphResponse,
    FullGraphResponse,
    ContextStateResponse,
    CompactionEvaluationResponse,
    CompactionResultResponse,
    ContextSummaryResponse,
    ContextRebuildResponse,
)
from app.utils.api_error import ApiError
from app.utils.db_queries import verify_ownership
from app.repositories import session_repo, source_repo
from app.api.limiter import limiter
from app.utils.session_utils import (
    get_session_with_auth,
    build_session_response,
    build_session_list_response,
)
from app.services.agents.streaming.response_handler import stream_agent_response
from app.services.agents.context import (
    delete_session_messages,
    get_context_state,
    evaluate_compaction,
    compact_session_context,
    get_context_summary,
    rebuild_session_context,
)
from app.core.config import get_neo4j_driver
from app.services.agents.graph_query_agent import run_graph_query
from app.utils.logger import logger

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ─────────────────────────────────────────────────────────────────────────
# Session CRUD Endpoints
# ─────────────────────────────────────────────────────────────────────────

@router.post(
    "/",
    response_model=ApiResponse,
    status_code=201,
)
@limiter.limit("5/minute")
async def create_session(
    request: Request,
    body: CreateSessionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new chat session.
    
    Title is optional and defaults to "Untitled".
    Session starts with no sources or messages.
    Sources can be attached before sending first message.
    
    Args:
        request: FastAPI request (required for rate limiting)
        body: CreateSessionRequest with optional title
        db: Database session
        current_user: Authenticated user
    
    Returns:
        ApiResponse with created SessionResponse
        Status: 201 Created
    
    Raises:
        ApiError(400): If title validation fails
    """
    # Trim title, default to "Untitled" if empty
    title = (body.title or "").strip() or "Untitled"
    
    # Create session via repository
    session = session_repo.create_session(db, current_user.id, title)
    
    # Build response
    response_data = SessionResponse.model_validate(session)
    return ApiResponse(
        statusCode=201,
        success=True,
        message="Chat session created successfully",
        data=response_data,
    )


@router.get("/", response_model=ApiResponse)
@limiter.limit("20/minute")
async def list_sessions(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all chat sessions for the authenticated user.
    
    Sessions are ordered by creation date (newest first).
    Includes attached sources for each session.
    
    Returns:
        ApiResponse with list of SessionResponse objects
    """
    sessions, _ = session_repo.get_sessions_by_user(db, current_user.id)
    sessions_data = build_session_list_response(db, sessions)
    
    return ApiResponse(
        statusCode=200,
        success=True,
        message="Sessions retrieved successfully",
        data=sessions_data,
    )


@router.get("/{session_id}", response_model=ApiResponse)
@limiter.limit("20/minute")
async def get_session(
    request: Request,
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get details of a specific chat session.
    
    Includes session metadata and attached sources.
    """
    session = await get_session_with_auth(db, session_id, current_user)
    response_data = build_session_response(db, session)
    
    return ApiResponse(
        statusCode=200,
        success=True,
        message="Session retrieved successfully",
        data=response_data,
    )


@router.patch("/{session_id}/title", response_model=ApiResponse)
@limiter.limit("5/minute")
async def rename_session(
    request: Request,
    session_id: UUID,
    body: RenameTitleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Rename a chat session's title.
    
    Can be called anytime, regardless of message count.
    """
    session = await get_session_with_auth(db, session_id, current_user)
    
    title = body.title.strip()
    if not title:
        raise ApiError(400, "Title cannot be empty")
    
    session = session_repo.update_session_title(db, session_id, title)
    response_data = build_session_response(db, session)
    
    return ApiResponse(
        statusCode=200,
        success=True,
        message="Session title updated successfully",
        data=response_data,
    )


@router.patch("/{session_id}/sources", response_model=ApiResponse)
@limiter.limit("5/minute")
async def attach_sources(
    request: Request,
    session_id: UUID,
    body: AttachSourcesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Attach sources to a chat session.
    
    Sources can only be attached if session has zero messages.
    This ensures the RAG context is immutable once chat begins.
    """
    session = await get_session_with_auth(db, session_id, current_user)
    
    # Validate: session must have zero messages
    message_count = session_repo.get_message_count(db, session.id)
    if message_count > 0:
        raise ApiError(
            400,
            "Cannot attach sources to session with existing messages. "
            "Create a new session to use different sources."
        )
    
    # Validate: all source IDs must exist and belong to current user
    sources = db.query(Source).filter(
        Source.id.in_(body.source_ids),
        Source.user_id == current_user.id
    ).all()
    
    if len(sources) != len(body.source_ids):
        raise ApiError(
            400,
            "One or more sources not found or do not belong to you"
        )
    
    # Attach sources (avoid duplicates)
    existing_ids = {s.id for s in session.sources}
    for source in sources:
        if source.id not in existing_ids:
            session.sources.append(source)

    db.commit()
    db.refresh(session)
    response_data = build_session_response(db, session)
    
    return ApiResponse(
        statusCode=200,
        success=True,
        message=f"Attached {len(sources)} source(s) to session",
        data=response_data,
    )

# Detach a source from a session using the DELETE route below.


@router.delete("/{session_id}/sources/{source_id}", response_model=ApiResponse)
@limiter.limit("5/minute")
async def detach_source_from_session(
    request: Request,
    session_id: UUID,
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Detach a source from a chat session.
    """
    session = await get_session_with_auth(db, session_id, current_user)

    source = source_repo.get_source_by_id(db, source_id)
    if not source:
        raise ApiError(404, "Source not found")

    verify_ownership(source.user_id, current_user.id, "source")

    # Prevent modification after chat starts
    message_count = session_repo.get_message_count(db, session.id)
    if message_count > 0:
        raise ApiError(
            400,
            "Cannot detach sources from a session with existing messages."
        )

    # Find source in session
    attached = next((s for s in session.sources if s.id == source.id), None)
    if not attached:
        raise ApiError(400, "Source not attached to this session")

    if len(session.sources) == 1:
        raise ApiError(400, "Session must have at least one source")

    session.sources.remove(attached)
    db.commit()
    db.refresh(session)

    response_data = build_session_response(db, session)
    
    return ApiResponse(
        statusCode=200,
        success=True,
        message="Source detached from session successfully",
        data=response_data,
    )


@router.delete("/{session_id}", response_model=ApiResponse)
@limiter.limit("5/minute")
async def delete_session(
    request: Request,
    session_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a chat session and all related messages.
    
    Cascade cleanup:
    1. Delete ChatMessage records from PostgreSQL
    2. Delete embedded messages from Qdrant (background, non-blocking)
    """
    session = await get_session_with_auth(db, session_id, current_user)
    session_repo.delete_session(db, session_id)
    
    # Schedule background task to clean up Qdrant (non-blocking)
    # Runs AFTER response is returned to user (zero latency impact)
    background_tasks.add_task(
        delete_session_messages,
        session_id=str(session_id),
    )
    
    return ApiResponse(
        statusCode=200,
        success=True,
        message="Session deleted successfully",
        data=None,
    )


# ─────────────────────────────────────────────────────────────────────────
# Message Endpoints
# ─────────────────────────────────────────────────────────────────────────

@router.post("/{session_id}/messages", status_code=200)
@limiter.limit("5/minute")
async def send_message(
    request: Request,
    session_id: UUID,
    body: SendMessageRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Send a message in a chat session with Server-Sent Events streaming.

    Streams the full RAG pipeline:
      1. Validates session and user ownership
      2. Persists user message to database
      3. Streams agent response (token-by-token)
      4. Streams tool invocations and results
      5. Persists assistant message
      6. Embeds both messages (non-blocking)

    Returns Server-Sent Events in format:
      - [PIPELINE] events during context building
      - [TOOL] events when tools are called/completed
      - Text chunks of agent response
      - [DONE] marker on completion
      - [ERROR] on failure

    Args:
        session_id: Chat session UUID
        body: Message content to send
        db: Database session
        current_user: Authenticated user

    Returns:
        StreamingResponse with text/event-stream media type

    Raises:
        404: Session not found
        403: Session doesn't belong to user
        400: Empty message content
    """
    # Validate session and ownership
    session = session_repo.get_session_by_id(db, session_id)
    if not session:
        raise ApiError(404, "Session not found")

    verify_ownership(session.user_id, current_user.id, "session")

    # Validate content
    content = body.content.strip()
    if not content:
        raise ApiError(400, "Message content cannot be empty")

    # Create user message immediately (persisted to DB)
    user_message = session_repo.add_user_message(db, session.id, content)

    # Return streaming response with SSE event stream
    return StreamingResponse(
        stream_agent_response(
            session_id=session_id,
            user_id=current_user.id,
            session=session,
            user_message_id=user_message.id,
            user_content=content,
            background_tasks=background_tasks,
            subgraph_mode=body.subgraph_mode,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.get("/{session_id}/messages", response_model=ApiResponse)
@limiter.limit("20/minute")
async def list_messages(
    request: Request,
    session_id: UUID,
    skip: int = Query(0, ge=0, description="Number of messages to skip"),
    limit: int = Query(50, ge=1, le=100, description="Maximum messages per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get paginated message history for a session.
    
    Messages are ordered by creation date (oldest first).
    Includes both user and assistant messages.
    
    Args:
        session_id: Session ID
        skip: Number of messages to skip (default 0)
        limit: Maximum messages to return (default 50, max 100)
        db: Database session
        current_user: Authenticated user
    
    Returns:
        ApiResponse with PaginatedMessagesResponse
    
    Raises:
        ApiError(404): If session not found
        ApiError(403): If session doesn't belong to user
    """
    session = session_repo.get_session_by_id(db, session_id)
    if not session:
        raise ApiError(404, "Session not found")
    
    verify_ownership(session.user_id, current_user.id, "session")
    
    # Get total count
    total = db.query(func.count(ChatMessage.id)).filter(
        ChatMessage.chat_id == session.id
    ).scalar() or 0
    
    # Query paginated messages (oldest first)
    messages = db.query(ChatMessage).filter(
        ChatMessage.chat_id == session.id
    ).order_by(ChatMessage.created_at.asc()).offset(skip).limit(limit).all()
    
    # Build response
    messages_data = [MessageResponse.model_validate(msg) for msg in messages]
    pagination = PaginationInfo(
        skip=skip,
        limit=limit,
        total=total,
        has_more=(skip + limit) < total,
    )
    
    response_data = PaginatedMessagesResponse(
        messages=messages_data,
        pagination=pagination,
    )
    
    return ApiResponse(
        statusCode=200,
        success=True,
        message="Messages retrieved successfully",
        data=response_data,
    )


# ─────────────────────────────────────────────────────────────────────────
# Knowledge Graph Endpoints
# ─────────────────────────────────────────────────────────────────────────

@router.post("/{session_id}/graph/query", response_model=ApiResponse)
@limiter.limit("5/minute")
async def graph_query(
    request: Request,
    session_id: UUID,
    body: GraphQueryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Query knowledge graph for a subgraph matching the query.
    
    Returns nodes and relationships scoped to sources attached to this session.
    Used by KG Studio panel for interactive visualization.
    
    Query can be natural language or Cypher syntax.
    
    Args:
        session_id: Session ID
        body: GraphQueryRequest with search query
        db: Database session
        current_user: Authenticated user
    
    Returns:
        ApiResponse with GraphResponse (nodes, edges, anchors)
    
    Raises:
        ApiError(404): If session not found
        ApiError(403): If session doesn't belong to user
        ApiError(400): If session has no attached sources or query is empty
    """
    session = session_repo.get_session_by_id(db, session_id)
    if not session:
        raise ApiError(404, "Session not found")
    
    verify_ownership(session.user_id, current_user.id, "session")
    
    # Validate: session must have sources
    if not session.sources:
        raise ApiError(
            400,
            "Cannot query graph. Session has no attached sources."
        )
    
    # Validate: query must be non-empty
    query = body.query.strip()
    if not query:
        raise ApiError(400, "Query cannot be empty")
    
    source_ids = [str(source.id) for source in session.sources]

    try:
        subgraph = await run_graph_query(
            query=query,
            source_ids=source_ids,
            max_nodes=body.max_nodes,
            hop_depth=body.hop_depth,
        )

        response_data = GraphResponse(
            nodes=[n.model_dump() for n in subgraph.nodes],
            edges=[e.model_dump() for e in subgraph.edges],
            anchor_ids=[n.id for n in subgraph.nodes],
            query=query,
            truncated=subgraph.truncated,
            reasoning=subgraph.reasoning,
            interpretation=subgraph.query_interpretation,
        )

        return ApiResponse(
            statusCode=200,
            success=True,
            message="Graph query executed successfully",
            data=response_data,
        )

    except Exception as e:
        logger.error(
            f"[GraphQuery] session={session_id} | query='{query}' | error: {e}",
            exc_info=True,
        )
        raise ApiError(500, f"Graph query failed: {str(e)}", code="GRAPH_QUERY_FAILED")


@router.get("/{session_id}/graph", response_model=ApiResponse)
@limiter.limit("20/minute")
async def get_full_graph(
    request: Request,
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get the full knowledge graph for a session.
    
    Returns all entities and relationships from sources attached to this session.
    Results are capped at 500 nodes; if exceeded, truncated flag is set.
    Used by KG viewer "show full graph" button.
    
    Args:
        session_id: Session ID
        db: Database session
        current_user: Authenticated user
    
    Returns:
        ApiResponse with FullGraphResponse (nodes, edges, truncated)
    
    Raises:
        ApiError(404): If session not found
        ApiError(403): If session doesn't belong to user
        ApiError(400): If session has no attached sources
    """
    session = session_repo.get_session_by_id(db, session_id)
    if not session:
        raise ApiError(404, "Session not found")
    
    verify_ownership(session.user_id, current_user.id, "session")
    
    # Validate: session must have sources
    if not session.sources:
        raise ApiError(
            400,
            "Cannot retrieve graph. Session has no attached sources."
        )
    
    source_ids = [str(source.id) for source in session.sources]

    try:
        driver = get_neo4j_driver()

        # Parameterized Cypher — scoped to session sources, no string interpolation
        cypher = """
        MATCH (n)-[r]->(m)
        WHERE n.source_id IN $source_ids
          AND m.source_id IN $source_ids
        RETURN n, r, m
        LIMIT 501
        """

        async with driver.session() as neo_session:
            result = await neo_session.run(cypher, source_ids=source_ids)
            records = await result.fetch(501)

        nodes_dict: dict = {}
        edges: list = []
        edges_set: set = set()

        for record in records[:500]:
            for value in record.values():
                if hasattr(value, "element_id") and hasattr(value, "labels"):
                    node_id = value.element_id
                    if node_id not in nodes_dict:
                        nodes_dict[node_id] = {
                            "id": node_id,
                            "label": next(iter(value.labels), "Unknown"),
                            "properties": dict(value),
                        }
                if hasattr(value, "start_node") and hasattr(value, "end_node"):
                    src = value.start_node.element_id
                    tgt = value.end_node.element_id
                    key = (src, tgt, value.type)
                    if key not in edges_set:
                        edges.append({
                            "source": src,
                            "target": tgt,
                            "type": value.type,
                            "properties": dict(value),
                        })
                        edges_set.add(key)

        nodes = list(nodes_dict.values())
        truncated = len(records) > 500

        if truncated:
            node_ids = {n["id"] for n in nodes}
            edges = [e for e in edges if e["source"] in node_ids and e["target"] in node_ids]

        response_data = FullGraphResponse(
            nodes=nodes,
            edges=edges,
            truncated=truncated,
            node_count=len(nodes),
            edge_count=len(edges),
        )

        logger.info(
            f"[FullGraph] session={session_id} | "
            f"nodes={len(nodes)}, edges={len(edges)}, truncated={truncated}"
        )

        return ApiResponse(
            statusCode=200,
            success=True,
            message="Full graph retrieved successfully",
            data=response_data,
        )

    except Exception as e:
        logger.error(f"[FullGraph] session={session_id} | error: {e}", exc_info=True)
        raise ApiError(500, f"Failed to retrieve graph: {str(e)}", code="GRAPH_RETRIEVAL_FAILED")


# ─────────────────────────────────────────────────────────────────────────
# Context Infrastructure / Debug Endpoints
# ─────────────────────────────────────────────────────────────────────────

@router.get("/{session_id}/context/state", response_model=ApiResponse)
@limiter.limit("20/minute")
async def get_session_context_state(
    request: Request,
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get the context state of a session for debugging/observability.

    Returns token usage, compaction threshold, usage percentage,
    window size, summary status, and compaction markers.

    Args:
        session_id: Session ID
        db: Database session
        current_user: Authenticated user

    Returns:
        ApiResponse with ContextStateResponse
    """
    session = await get_session_with_auth(db, session_id, current_user)

    state = await get_context_state(session_id, db)

    response_data = ContextStateResponse(**state)

    return ApiResponse(
        statusCode=200,
        success=True,
        message="Context state retrieved successfully",
        data=response_data,
    )


@router.post("/{session_id}/context/evaluate", response_model=ApiResponse)
@limiter.limit("10/minute")
async def evaluate_session_compaction(
    request: Request,
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Evaluate whether compaction is needed for a session.

    Estimates current token usage, compares with threshold.
    If exceeded, marks session.needs_compaction = true.

    Args:
        session_id: Session ID
        db: Database session
        current_user: Authenticated user

    Returns:
        ApiResponse with CompactionEvaluationResponse
    """
    session = await get_session_with_auth(db, session_id, current_user)

    result = await evaluate_compaction(session_id, db)

    response_data = CompactionEvaluationResponse(**result)

    return ApiResponse(
        statusCode=200,
        success=True,
        message="Compaction evaluation completed",
        data=response_data,
    )


@router.post("/{session_id}/context/compact", response_model=ApiResponse)
@limiter.limit("5/minute")
async def compact_session(
    request: Request,
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Manually trigger context compaction for a session.

    Workflow:
      1. Load old messages before compact boundary
      2. Generate/update rolling summary
      3. Update session metadata
      4. Preserve recent messages untouched

    Reuses existing summarizer and budgeting logic.

    Args:
        session_id: Session ID
        db: Database session
        current_user: Authenticated user

    Returns:
        ApiResponse with CompactionResultResponse
    """
    session = await get_session_with_auth(db, session_id, current_user)

    result = await compact_session_context(session_id, db)

    response_data = CompactionResultResponse(**result)

    return ApiResponse(
        statusCode=200,
        success=True,
        message="Compaction completed" if result.get("compacted") else "Compaction not needed",
        data=response_data,
    )


@router.get("/{session_id}/context/summary", response_model=ApiResponse)
@limiter.limit("20/minute")
async def get_session_context_summary(
    request: Request,
    session_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get the rolling summary and metadata for a session.

    Infrastructure/debug route.

    Args:
        session_id: Session ID
        db: Database session
        current_user: Authenticated user

    Returns:
        ApiResponse with ContextSummaryResponse
    """
    session = await get_session_with_auth(db, session_id, current_user)

    result = await get_context_summary(session_id, db)

    response_data = ContextSummaryResponse(**result)

    return ApiResponse(
        statusCode=200,
        success=True,
        message="Context summary retrieved successfully",
        data=response_data,
    )


@router.post("/{session_id}/context/rebuild", response_model=ApiResponse)
@limiter.limit("2/minute")
async def rebuild_session_context_route(
    request: Request,
    session_id: UUID,
    db: Session = Depends(get_db),
    admin_user: User = Depends(get_current_admin),
):
    """
    Rebuild session context state from transcript (admin only).

    Recovery/admin route. NOT used during normal operation.
    Clears existing summary and recomputes context state from message history.
    Requires admin privileges.

    Args:
        session_id: Session ID
        db: Database session
        admin_user: Authenticated admin user

    Returns:
        ApiResponse with ContextRebuildResponse
    """
    session = session_repo.get_session_by_id(db, session_id)
    if not session:
        raise ApiError(404, "Session not found")

    result = await rebuild_session_context(session_id, db)

    response_data = ContextRebuildResponse(**result)

    return ApiResponse(
        statusCode=200,
        success=True,
        message="Context rebuilt successfully",
        data=response_data,
    )

