"""
SSE streaming response handler for agent chat sessions.

Orchestrates context building, agent execution, and event streaming.
"""

import asyncio
from uuid import UUID
from fastapi import BackgroundTasks
from app.models.chat_session import ChatSession
from app.services.agents.pipeline import run_agent_pipeline_stream, embed_turn_messages
from app.repositories import session_repo
from app.services.agents.streaming.event_handler import (
    process_queue_events,
    format_done_event,
    format_error_event,
    collect_agent_chunks,
)
from app.utils.logger import logger


async def _background_compaction_check(session_id: str) -> None:
    """
    Background task: evaluate + compact session if needed.

    Non-blocking, non-fatal. Runs after response is returned to user.
    Creates its own DB session (request-scoped session may be closed).
    """
    from app.db.session import get_db_session
    from app.services.agents.context.session_context_service import (
        evaluate_compaction,
        compact_session_context,
    )

    try:
        with get_db_session() as db:
            result = await evaluate_compaction(UUID(session_id), db)

            if result.get("needs_compaction"):
                compact_result = await compact_session_context(UUID(session_id), db)
                logger.info(
                    f"[BackgroundCompaction] session={session_id} | "
                    f"compacted={compact_result.get('compacted')} | "
                    f"msgs={compact_result.get('messages_compacted', 0)}"
                )

    except Exception as e:
        # Non-fatal — compaction will be retried on next evaluation
        logger.error(f"[BackgroundCompaction] Failed for session={session_id}: {e}")


async def stream_agent_response(
    session_id: UUID,
    user_id: UUID,
    session: ChatSession,
    user_message_id: UUID,
    user_content: str,
    background_tasks: BackgroundTasks,
    subgraph_mode: bool = False,
):
    """
    Generate SSE stream of pipeline events, tool events, and message content.

    Yields different event types for rich UX:
      1. Pipeline events: context building stages (LOADING, ESTIMATING, COMPACTING, ASSEMBLING)
      2. Tool events: tool calls and results
      3. Message text chunks: token-by-token content
      4. Completion marker: [DONE]

    Architecture:
      - Creates asyncio.Queue for pipeline events
      - Sets it in context for pipeline stages to emit into
      - Runs agent pipeline in background task
      - Concurrently yields formatted SSE events
      - After streaming: persists message
      - Schedules background tasks: embeddings + compaction evaluation (non-blocking)

    Args:
        session_id: Chat session UUID
        user_id: User UUID
        session: ChatSession ORM object
        user_message_id: UUID of user message (already created)
        user_content: User message text content
        background_tasks: FastAPI BackgroundTasks for non-blocking embedding

    Yields:
        SSE-formatted strings: "data: {content}\n\n"
    """
    from app.services.agents.context.events import set_event_queue
    from app.db.session import get_db_session

    event_queue: asyncio.Queue = asyncio.Queue()
    await set_event_queue(event_queue)

    try:
        # Start agent pipeline (emits both pipeline + tool events)
        agent_stream = run_agent_pipeline_stream(
            user_id=str(user_id),
            session=session,
            chat_id=session_id,
            user_message=user_content,
            subgraph_mode=subgraph_mode,
        )

        # Collect agent chunks in background and forward to queue
        agent_task = asyncio.create_task(
            collect_agent_chunks(agent_stream, event_queue)
        )

        # Process and yield events as SSE
        async for sse_line in process_queue_events(event_queue, timeout=60.0):
            yield sse_line

        # Get accumulated response from agent task
        full_response = await agent_task

        # Persist assistant message to database
        with get_db_session() as db:
            assistant_message = session_repo.add_assistant_message(
                db,
                session_id,
                full_response.strip(),
            )

        # Schedule background task to embed both messages concurrently
        # This runs AFTER response is returned to user (zero latency impact)
        background_tasks.add_task(
            embed_turn_messages,
            session_id=str(session_id),
            user_message_id=str(user_message_id),
            user_content=user_content,
            assistant_message_id=str(assistant_message.id),
            assistant_content=full_response.strip(),
        )

        # Schedule background compaction evaluation
        # Checks if session needs compaction and compacts if threshold exceeded
        # Non-blocking, non-fatal (zero latency impact)
        background_tasks.add_task(
            _background_compaction_check,
            session_id=str(session_id),
        )

        # Send completion marker immediately (no wait for Qdrant or compaction)
        yield format_done_event()

    except Exception as e:
        yield format_error_event(str(e))
        logger.error(f"[StreamError] session={session_id} | user={user_id} | {e}")

