"""
Agent pipeline orchestrator.

Responsibilities:
  1. Resolve session sources (collection_names + source_ids)
  2. Build context window (delegated to context.manager via context package)
  3. Run agent (delegated entirely to chat_agent.py)
  4. Return reply string

NOT responsible for:
  - Summarization (context pipeline handles it)
  - Embedding (called as BackgroundTask from the route)
  - Memory management (agent tools handle it)

Context pipeline (context/ package):
  Implements Claude-style rolling conversation runtime with these stages:
    1. Load state (summary + recent messages)
    2. Estimate token budget
    3. Compact if needed (before agent runs)
    4. Assemble final context
    5. Return to agent

  No semantic chat retrieval (disabled by default).
  All stages have observable event hooks for future streaming.

Embedding:
  embed_turn_messages is called as a FastAPI BackgroundTask from the route
  AFTER the response is committed and returned to the user.
  It creates its own DB session — never receives the request-scoped session.
"""

import asyncio
from uuid import UUID

from app.db.session import get_db_session
from app.models.chat_session import ChatSession
from app.models.source_index import SourceIndex
from app.utils.api_error import ApiError

from app.services.agents.context import build_context_window, embed_message
from app.services.agents.chat_agent import run_agent, run_agent_stream
from app.utils.logger import logger


# ─────────────────────────────────────────────────────────────────────────
# Source Resolution
# ─────────────────────────────────────────────────────────────────────────

def _resolve_sources(
    session: ChatSession,
    db,
) -> tuple[list[str], list[str]]:
    """
    Resolve Qdrant collection names and Neo4j source_ids for the session.

    Rules:
      - collection_names → sources where vector_indexed=True only
      - source_ids       → sources where graph_indexed=True only

    A source in "indexing" status (vector done, graph pending) appears in
    vector_search but NOT graph_search — graceful degradation.

    Returns:
        (collection_names, source_ids)
    """
    collection_names: list[str] = []
    source_ids: list[str] = []

    for source in session.sources:
        index = (
            db.query(SourceIndex)
            .filter(SourceIndex.source_id == source.id)
            .first()
        )
        if not index:
            continue

        if index.vector_indexed:
            collection_names.append(index.collection_name)

        if index.graph_indexed:
            source_ids.append(str(source.id))

    return collection_names, source_ids


def _resolve_graph_source_ids_for_subgraph(
    all_graph_source_ids: list[str],
    selected_source_ids: list[str] | None,
) -> list[str]:
    """
    Compute the Neo4j source_ids that the subgraph_query tool should use.

    Rules:
      - If selected_source_ids is None or empty → use all graph-indexed IDs
      - Otherwise → intersect selected_source_ids with graph-indexed IDs
        (only selected sources that are actually graph-indexed get queried)

    This ensures we never pass IDs that are not graph-indexed to Neo4j,
    and we respect the user's canvas source selection.

    Args:
        all_graph_source_ids: All graph-indexed source IDs for the session
        selected_source_ids:  Source IDs chosen by user in the Sources panel

    Returns:
        List of source IDs to scope the subgraph_query to
    """
    if not selected_source_ids:
        return all_graph_source_ids  # no selection → use all

    selected_set = set(selected_source_ids)
    return [sid for sid in all_graph_source_ids if sid in selected_set]


# ─────────────────────────────────────────────────────────────────────────
# Main Pipeline (Non-streaming)
# ─────────────────────────────────────────────────────────────────────────

async def run_agent_pipeline(
    user_id: str,
    session: ChatSession,
    chat_id: UUID,
    user_message: str,
) -> str:
    """
    Full pipeline: user message → agent reply.

    Steps:
      1. Open a short-lived DB session to resolve sources + build context window
      2. Close DB session before running the agent (agent may take seconds)
      3. Run agent with pre-built context
      4. Return reply

    DB session is closed before agent execution — no long-held connections
    during LLM inference time.

    Args:
        user_id:      User UUID string (scopes Mem0 memory)
        session:      ChatSession ORM object (with .sources pre-loaded)
        chat_id:      UUID of the chat session
        user_message: The current user message text

    Returns:
        Agent reply string

    Raises:
        ApiError(500): On unrecoverable failure
    """
    try:
        with get_db_session() as db:
            # Step 1: Resolve which sources are ready for retrieval
            collection_names, source_ids = _resolve_sources(session, db)

            # Step 2: Build context window
            # context.py handles: DB fetch, split, summarize, semantic search
            context_window = await build_context_window(
                session_id=chat_id,
                current_user_message=user_message,
                db=db,
            )
        # DB session closed here — agent runs outside the connection

        # Step 3: Run agent with pre-built context
        reply = await run_agent(
            user_id=user_id,
            messages=context_window,
            collection_names=collection_names,
            source_ids=source_ids,
            chat_id=str(chat_id),
        )

        return reply

    except ApiError:
        raise
    except Exception as e:
        logger.error(f"[Pipeline] Unexpected error | session={chat_id} | user={user_id} | {e}")
        raise ApiError(status_code=500, detail="Agent pipeline failed unexpectedly")


# ─────────────────────────────────────────────────────────────────────────
# Main Pipeline (Streaming)
# ─────────────────────────────────────────────────────────────────────────

async def run_agent_pipeline_stream(
    user_id: str,
    session: ChatSession,
    chat_id: UUID,
    user_message: str,
    subgraph_mode: bool = False,
    selected_source_ids: list[str] | None = None,
):
    """
    Streaming pipeline: user message → agent reply (token-by-token).

    Identical to run_agent_pipeline but yields text chunks instead of returning full reply.

    Steps:
      1. Open a short-lived DB session to resolve sources + build context window
      2. Close DB session before running the agent (agent may take seconds)
      3. Run agent with streaming, yield text chunks
      4. Return full reply via async generator

    When subgraph_mode=True and selected_source_ids is provided, the graph_source_ids
    passed to the subgraph_query tool are restricted to the intersection of:
      - graph-indexed source IDs for this session
      - user-selected source IDs (from the Sources panel checkboxes)
    Standalone chat tools (vector_search, graph_search) always use all session sources.

    DB session is closed before agent streaming starts — no long-held connections
    during LLM inference time.

    Args:
        user_id:             User UUID string (scopes Mem0 memory)
        session:             ChatSession ORM object (with .sources pre-loaded)
        chat_id:             UUID of the chat session
        user_message:        The current user message text
        subgraph_mode:       Whether graph panel sync is enabled
        selected_source_ids: Source IDs selected in the UI (scopes subgraph_query only)

    Yields:
        Text chunks from agent response (strings)

    Raises:
        ApiError(500): On unrecoverable failure
    """
    try:
        with get_db_session() as db:
            # Step 1: Resolve which sources are ready for retrieval
            collection_names, source_ids = _resolve_sources(session, db)

            # Step 2: Build context window
            # context.py handles: DB fetch, split, summarize, semantic search
            context_window = await build_context_window(
                session_id=chat_id,
                current_user_message=user_message,
                db=db,
            )
        # DB session closed here — agent stream runs outside the connection

        # Compute graph source IDs for the subgraph_query tool.
        # In subgraph_mode with a user selection: use the intersection.
        # Otherwise: same as source_ids (all graph-indexed sources).
        if subgraph_mode and selected_source_ids:
            graph_source_ids = _resolve_graph_source_ids_for_subgraph(
                all_graph_source_ids=source_ids,
                selected_source_ids=selected_source_ids,
            )
            logger.info(
                f"[Pipeline] subgraph_mode scoping: "
                f"all_graph={source_ids} selected={selected_source_ids} "
                f"→ graph_source_ids={graph_source_ids}"
            )
        else:
            graph_source_ids = source_ids

        # Step 3: Stream agent with pre-built context
        async for chunk in run_agent_stream(
            user_id=user_id,
            messages=context_window,
            collection_names=collection_names,
            source_ids=source_ids,
            graph_source_ids=graph_source_ids,
            chat_id=str(chat_id),
            subgraph_mode=subgraph_mode,
        ):
            yield chunk

    except ApiError:
        raise
    except Exception as e:
        logger.error(f"[Pipeline] Streaming error | session={chat_id} | user={user_id} | {e}")
        raise ApiError(500, "Agent streaming pipeline failed unexpectedly")


# ─────────────────────────────────────────────────────────────────────────
# Background Task: Embed turn messages into Qdrant (used only if agent response is non-streaming)
# ─────────────────────────────────────────────────────────────────────────

async def embed_turn_messages(
    session_id: str,
    user_message_id: str,
    user_content: str,
    assistant_message_id: str,
    assistant_content: str,
) -> None:
    """
    Embed both messages from this turn into the shared Qdrant chat_messages collection.

    Called as a FastAPI BackgroundTask from the route, AFTER:
      - assistant reply is saved to DB
      - response is returned to the user

    This means embedding adds ZERO latency to the user's experience.

    Creates its own DB session — NEVER receives the request-scoped session.
    The request-scoped session may already be closed by the time this runs.

    Non-fatal: Qdrant write failures are logged but do not raise. PostgreSQL
    remains the source of truth. The next turn will simply not find these
    messages in semantic search (graceful degradation).

    Args:
        session_id:           UUID string — stored as chat_id payload in Qdrant
        user_message_id:      UUID string — used as Qdrant point ID
        user_content:         User message text
        assistant_message_id: UUID string — used as Qdrant point ID
        assistant_content:    Assistant reply text
    """
    # Embed both messages concurrently — independent operations
    results = await asyncio.gather(
        embed_message(
            session_id=session_id,
            message_id=user_message_id,
            role="user",
            content=user_content,
        ),
        embed_message(
            session_id=session_id,
            message_id=assistant_message_id,
            role="assistant",
            content=assistant_content,
        ),
        return_exceptions=True,  # one failure must not cancel the other
    )

    # Log any exceptions (gather with return_exceptions=True swallows them)
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            role = "user" if i == 0 else "assistant"
            logger.error(f"[Pipeline] embed_turn_messages failed for {role} message: {result}")