"""
Event processing and SSE formatting for streaming responses.
Consolidates event type handling and SSE response building.
"""

import asyncio
import json
from typing import AsyncGenerator, Any


async def process_queue_events(
    event_queue: asyncio.Queue,
    timeout: float = 60.0,
) -> AsyncGenerator[str, None]:
    """
    Process events from queue and format as SSE.
    
    Handles all event types:
      - "text": Message text chunks
      - "tool_call": Tool invocation events
      - "tool_output": Tool result events
      - "pipeline": Context building stages
      - "done": Completion marker
    
    Args:
        event_queue: asyncio.Queue with (event_type, event_data) tuples
        timeout: Timeout per event retrieval in seconds
    
    Yields:
        SSE-formatted strings: "data: {content}\n\n"
    
    Raises:
        asyncio.TimeoutError: If no event received within timeout
    """
    while True:
        try:
            # Wait for next event with timeout
            event_type, event_data = await asyncio.wait_for(
                event_queue.get(),
                timeout=timeout,
            )

            if event_type == "done":
                # Agent streaming complete
                break
            
            # Format and yield based on event type
            sse_line = format_event_as_sse(event_type, event_data)
            if sse_line:
                yield sse_line

        except asyncio.TimeoutError:
            yield format_error_event("Stream timeout")
            break


def format_event_as_sse(event_type: str, event_data: Any) -> str:
    """
    Format an event as Server-Sent Event string.
    
    Args:
        event_type: Type of event ("text", "tool_call", "tool_output", "pipeline")
        event_data: Event payload
    
    Returns:
        SSE-formatted string or empty string if unknown type
    """
    if event_type == "text":
        # Message text chunk (raw)
        return f"data: {event_data}\n\n"
    
    elif event_type == "tool_call":
        # Tool invocation: {"tool_name": str, ...}
        tool_json = json.dumps(event_data)
        return f"data: [TOOL] call {tool_json}\n\n"
    
    elif event_type == "tool_output":
        # Tool result: {"tool_name": str, "output": str}
        tool_json = json.dumps(event_data)
        return f"data: [TOOL] output {tool_json}\n\n"
    
    elif event_type == "pipeline":
        # Context stage: {"type": str, "session_id": str, "payload": dict}
        pipeline_json = json.dumps(event_data)
        return f"data: [PIPELINE] {pipeline_json}\n\n"
    
    return ""  # Unknown event type


def format_error_event(message: str) -> str:
    """Format an error event as SSE."""
    return f"data: [ERROR] {message}\n\n"


def format_done_event() -> str:
    """Format completion marker as SSE."""
    return "data: [DONE]\n\n"


async def collect_agent_chunks(
    agent_stream: AsyncGenerator,
    event_queue: asyncio.Queue,
) -> str:
    """
    Read from agent stream and forward events to queue.
    
    Consolidates agent stream events (text, tool_call, tool_output)
    into the event_queue for unified processing.
    
    Args:
        agent_stream: Async generator from run_agent_pipeline_stream()
        event_queue: Queue to put events into
    
    Returns:
        Accumulated full response text
    
    Raises:
        Any exceptions from agent_stream iteration
    """
    full_response = ""
    
    try:
        async for event_tuple in agent_stream:
            # Validate tuple format
            if not isinstance(event_tuple, tuple) or len(event_tuple) != 2:
                print(f"[StreamWarn] Unexpected event format: {event_tuple}")
                continue

            event_type, event_data = event_tuple

            # Forward agent events to queue
            if event_type == "text":
                full_response += event_data
                await event_queue.put(("text", event_data))
            elif event_type == "tool_call":
                await event_queue.put(("tool_call", event_data))
            elif event_type == "tool_output":
                await event_queue.put(("tool_output", event_data))
    
    finally:
        # Signal completion
        await event_queue.put(("done", None))
    
    return full_response
