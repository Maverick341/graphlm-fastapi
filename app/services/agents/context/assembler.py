"""
Final context window assembly.

Combines summary, semantic results (if any), and recent messages
into the final list that gets passed to the agent.

Simple, focused: no trimming or complex logic (that happens upstream).
"""


def assemble_context_window(
    summary: str | None,
    recent_messages: list[dict],
    semantic_messages: list[dict] | None = None,
) -> list[dict]:
    """
    Assemble the final context window for the agent.
    
    Order (chronologically from oldest to newest):
      1. [summary]          - if it exists
      2. [semantic results] - if available and enabled
      3. [recent messages]  - always included
    
    Args:
        summary: Rolling summary text or None
        recent_messages: Recent message dicts (always included)
        semantic_messages: Optional list of semantic search results
    
    Returns:
        Final context list: [{"role": str, "content": str}, ...]
        Ready to pass to the agent runner
    """
    context: list[dict] = []
    
    # Add summary if it exists
    if summary:
        context.append({
            "role": "system",
            "content": summary
        })
    
    # Add semantic results if available
    if semantic_messages:
        context.extend(semantic_messages)
    
    # Always add recent messages (never trimmed)
    context.extend(recent_messages)
    
    return context
