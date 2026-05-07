"""
Pipeline event types and emitter for observable conversation runtime.

These events mark the stages of context building and agent execution.
Events can be emitted to a request-scoped async queue for SSE streaming.

Context variable approach:
  - Request handler sets event queue in context
  - Pipeline stages emit events to the queue
  - SSE generator yields events from the queue
  - Clean separation of concerns with contextvars

For development/testing without streaming:
  - Events are logged to console if queue is not set
"""

import asyncio
from enum import Enum
from typing import Optional
from contextvars import ContextVar
import json

# Request-scoped event queue (set by streaming endpoint)
_event_queue: ContextVar[Optional[asyncio.Queue]] = ContextVar(
    "_event_queue",
    default=None,
)


class PipelineEventType(str, Enum):
    """
    Lifecycle events in the conversation runtime pipeline.
    
    Streaming flow:
      FETCHING_HISTORY
      → LOADING_STATE
      → ESTIMATING_BUDGET
      → COMPACTING_CONTEXT (if needed)
      → ASSEMBLING_CONTEXT
      → RUNNING_AGENT
      → STREAMING_RESPONSE (future)
    """
    FETCHING_HISTORY = "fetching_history"
    LOADING_STATE = "loading_state"
    ESTIMATING_BUDGET = "estimating_budget"
    COMPACTING_CONTEXT = "compacting_context"
    ASSEMBLING_CONTEXT = "assembling_context"
    RUNNING_AGENT = "running_agent"
    STREAMING_RESPONSE = "streaming_response"


async def set_event_queue(queue: asyncio.Queue) -> None:
    """
    Set the event queue for the current async context.
    
    Called by the streaming endpoint before starting the pipeline.
    
    Args:
        queue: asyncio.Queue to put events into
    """
    _event_queue.set(queue)


async def emit_pipeline_event(
    event_type: PipelineEventType,
    session_id: str,
    payload: Optional[dict] = None,
) -> None:
    """
    Emit a pipeline event for observability and streaming.

    If an event queue is set in context (streaming mode):
      - Puts SSE-formatted event in the queue
      - Returns immediately (non-blocking)

    If no queue is set (development mode):
      - Logs event to console for debugging

    Args:
        event_type: The PipelineEventType that occurred
        session_id: Chat session UUID (for client routing)
        payload: Optional dict with event-specific data
                 e.g., {"tokens_used": 1234, "summary_updated": True}

    Example:
        # In context/manager.py:
        await emit_pipeline_event(
            PipelineEventType.COMPACTING_CONTEXT,
            session_id_str,
            {"messages_compacted": 5, "new_tokens": 234}
        )

        # This will either:
        # (a) Put event in queue if streaming enabled
        # (b) Print to console if not streaming
    """
    queue = _event_queue.get()

    # Build event data
    event_data = {
        "type": event_type.value,
        "session_id": session_id,
        "payload": payload or {},
    }

    if queue:
        # Streaming mode: put event in queue as (event_type, event_data) tuple
        # Matches format from run_agent_stream() for consistent unpacking
        await queue.put(("pipeline", event_data))
    else:
        # Debug mode: just log
        print(
            f"[PipelineEvent] {event_type.value} | "
            f"session={session_id} | "
            f"{payload or {}}"
        )
