"""
Token estimation and budget management.

Centralizes all token counting logic and budget threshold decisions.
Single source of truth for context window capacity planning.
"""

import tiktoken
from app.core.config import settings

# Module-level tokenizer (cached after first use)
_tokenizer = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """
    Count tokens in text using cl100k_base encoding.
    Works for all OpenAI models (GPT-4, GPT-4o, etc.)
    
    Args:
        text: The text to count tokens for
    
    Returns:
        Number of tokens
    """
    return len(_tokenizer.encode(text))


def count_messages_tokens(messages: list[dict]) -> int:
    """
    Sum token count across a list of message dicts.
    Adds 4 tokens per message for role/content separator overhead.
    
    Args:
        messages: List of {"role": str, "content": str} dicts
    
    Returns:
        Total token count including per-message overhead
    """
    total = 0
    for m in messages:
        total += count_tokens(m.get("role", ""))
        total += count_tokens(m.get("content", ""))
        total += 4  # per-message overhead (role, content, separator markers)
    return total


def get_available_context_budget() -> int:
    """
    Compute the available token budget for the context window.
    
    Calculated as:
      available = (MODEL_MAX_TOKENS * CONTEXT_SAFE_RATIO)
                - CONTEXT_RESERVED_FOR_RAG
                - CONTEXT_RESERVED_FOR_RESPONSE
    
    Returns:
        Number of tokens available for context assembly
    """
    max_context = int(settings.MODEL_MAX_TOKENS * settings.CONTEXT_SAFE_RATIO)
    return (
        max_context
        - settings.CONTEXT_RESERVED_FOR_RAG
        - settings.CONTEXT_RESERVED_FOR_RESPONSE
    )


def get_system_prompt_budget() -> int:
    """
    Get the token budget reserved for the system prompt and tool descriptions.
    
    Returns:
        Token budget (default 1000 if not set in settings)
    """
    return getattr(settings, "SYSTEM_PROMPT_BUDGET", 1_000)


def estimate_tokens(
    summary: str | None,
    recent_messages: list[dict],
    semantic_messages: list[dict] | None = None,
) -> dict:
    """
    Estimate token usage for a proposed context window.
    
    Args:
        summary: Rolling summary text or None
        recent_messages: Recent message dicts (always included)
        semantic_messages: Optional semantic search results
    
    Returns:
        Dict with token breakdown:
        {
            "summary_tokens": int,
            "recent_tokens": int,
            "semantic_tokens": int,
            "system_budget": int,
            "total": int,
            "available": int,
            "headroom": int,
            "exceeded": bool,
        }
    """
    summary_tokens = count_tokens(summary) if summary else 0
    recent_tokens = count_messages_tokens(recent_messages)
    semantic_tokens = count_messages_tokens(semantic_messages or [])
    system_budget = get_system_prompt_budget()
    available = get_available_context_budget()
    
    total = summary_tokens + recent_tokens + semantic_tokens + system_budget
    
    return {
        "summary_tokens": summary_tokens,
        "recent_tokens": recent_tokens,
        "semantic_tokens": semantic_tokens,
        "system_budget": system_budget,
        "total": total,
        "available": available,
        "headroom": available - total,
        "exceeded": total > available,
    }


def should_compact(token_estimate: dict) -> bool:
    """
    Determine if context compaction is necessary.
    
    Args:
        token_estimate: Dict returned by estimate_tokens()
    
    Returns:
        True if total tokens exceed available budget
    """
    return token_estimate["exceeded"]
