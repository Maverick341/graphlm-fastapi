"""
Pipeline event types and emitter for observable conversation runtime.

These events mark the stages of context building and agent execution.
Currently placeholders for future streaming integration (SSE/WebSocket).

For now, events can be uncommented in manager.py for debug logging.
Later, emit_pipeline_event() will broadcast to connected clients.
"""

from enum import Enum
from typing import Optional


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


async def emit_pipeline_event(
    event_type: PipelineEventType,
    session_id: str,
    payload: Optional[dict] = None,
) -> None:
    """
    Emit a pipeline event for observability and streaming.
    
    PLACEHOLDER: Currently does nothing.
    
    Future integration points:
      - FastAPI background task to SSE endpoint
      - WebSocket broadcast to connected clients
      - Redis pub/sub for distributed systems
      - Metrics collection (Prometheus, DataDog)
    
    Args:
        event_type: The PipelineEventType that occurred
        session_id: Chat session UUID (for client routing)
        payload: Optional dict with event-specific data
                 e.g., {"tokens_used": 1234, "summary_updated": True}
    
    Example:
        # In manager.py, uncomment to enable:
        # await emit_pipeline_event(
        #     PipelineEventType.COMPACTING_CONTEXT,
        #     session_id_str,
        #     {"messages_compacted": 5, "new_tokens": 234}
        # )
    """
    # TODO: Implement streaming transport
    # print(f"[PipelineEvent] {event_type.value} | session={session_id} | {payload or {}}")
    pass
