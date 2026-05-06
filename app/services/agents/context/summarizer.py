"""
Rolling conversation summarization.

Compacts old messages into a rolling summary that chains previous summaries.

Key insight: When generating a new summary, the previous summary is prepended
as a system message so the new summary inherits all previously compressed knowledge.

This creates a rolling summary chain: summary_v1 → summary_v2 → summary_v3 → ...

Without this chaining, each new summary would only cover the current batch of
old messages, discarding everything that was previously compressed.
"""

import openai
from uuid import UUID
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings

_openai = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def call_summarizer(
    messages_to_summarize: list[dict],
    previous_summary: str | None = None,
) -> str:
    """
    Generate a bullet-point summary of messages.
    
    If previous_summary is provided, it's prepended as a system message
    so the new summary inherits all previously compressed knowledge.
    
    This creates the rolling chain: v1 → v2 → v3 → ...
    
    Args:
        messages_to_summarize: List of {"role", "content"} dicts to summarize
        previous_summary: Optional previous summary text (chained into input)
    
    Returns:
        New summary text prefixed with "[SUMMARY]"
    """
    # ── Chain previous summary ──────────────────────────────────────────
    # Prepend the old summary as a system message so the new summary
    # covers old compressed knowledge + new messages together
    input_msgs = messages_to_summarize
    if previous_summary:
        input_msgs = [
            {"role": "system", "content": previous_summary}
        ] + messages_to_summarize
    
    conversation_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in input_msgs
    )
    
    response = await _openai.chat.completions.create(
        model=settings.OPENAI_LLM_MODEL,
        max_tokens=600,
        temperature=0,  # deterministic output for stability
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a conversation summarizer. "
                    "Summarize the conversation into a concise bullet-point list "
                    "of key facts, decisions, preferences, technologies, and topics. "
                    "Preserve all technical details, entity names, and specifics. "
                    "Output only the bullet list — no preamble or introduction."
                ),
            },
            {
                "role": "user",
                "content": f"Conversation to summarize:\n\n{conversation_text}",
            },
        ],
    )
    
    return "[SUMMARY]\n" + response.choices[0].message.content


async def compact_and_merge_summary(
    session_id: UUID,
    older_messages: list[dict],
    previous_summary: str | None,
    db: DBSession,
) -> str:
    """
    Compact the oldest message chunk into the rolling summary.
    
    Pipeline:
      1. Call LLM to generate new summary (chaining previous if exists)
      2. Persist to DB via state.update_summary()
      3. Return new summary text
    
    Args:
        session_id: Chat session UUID
        older_messages: List of {"role", "content"} dicts to compact
        previous_summary: Existing rolling summary (or None)
        db: SQLAlchemy session (unused here, kept for future extension)
    
    Returns:
        New summary text (prefixed with "[SUMMARY]")
    
    Raises:
        openai.APIError: If LLM call fails
    """
    new_summary = await call_summarizer(older_messages, previous_summary)
    return new_summary
