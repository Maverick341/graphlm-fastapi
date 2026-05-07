"""
Pipeline manager: orchestrates the Claude-style rolling conversation runtime.

Main entry point: build_context_window()

Pipeline stages:
  1. Load state (summary + recent messages from DB)
  2. Estimate token budget
  3. Compact if needed (before agent runs)
  4. Assemble final context
  5. Return to agent

Event hooks are commented out but placed strategically for future streaming integration.
Uncomment to enable SSE/WebSocket events.
"""

from uuid import UUID
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings

# Pipeline components
from .events import PipelineEventType, emit_pipeline_event
from .state import ConversationState, load_older_messages_for_compaction
from .budgeting import estimate_tokens, should_compact
from .summarizer import compact_and_merge_summary
from .assembler import assemble_context_window
from .optional_retrieval import retrieve_semantic_messages


async def build_context_window(
    session_id: UUID,
    current_user_message: str,
    db: DBSession,
) -> list[dict]:
    """
    Build context window for the agent (Claude-style rolling conversation).
    
    Implements the rolling conversation runtime architecture:
      - Load existing summary and recent messages
      - Estimate token budget
      - Compact if over budget (BEFORE agent runs)
      - Assemble final context
      - Return to agent
    
    Key behaviors:
      - Summarization is stateful (persistent in DB)
      - Compaction happens incrementally (rolling summary chain)
      - Recent messages stay small and fast
      - Semantic search is optional (disabled by default)
      - All stages have observable event hooks (for future streaming)
    
    Args:
        session_id: Chat session UUID
        current_user_message: User's current message (used for semantic query)
        db: SQLAlchemy session
    
    Returns:
        Final context list: [{role, content}, ...]
        Ready to pass directly to the agent runner
    
    Raises:
        Exception: On unrecoverable failures (will be caught upstream)
    """
    session_id_str = str(session_id)
    
    # ──────────────────────────────────────────────────────────────────
    # Stage 1: Load state
    # ──────────────────────────────────────────────────────────────────
    await emit_pipeline_event(PipelineEventType.LOADING_STATE, session_id_str)
    
    state = await ConversationState.load_from_db(session_id, db)
    
    # ──────────────────────────────────────────────────────────────────
    # Stage 2: Estimate budget
    # ──────────────────────────────────────────────────────────────────
    await emit_pipeline_event(PipelineEventType.ESTIMATING_BUDGET, session_id_str)
    
    token_estimate = estimate_tokens(
        state.rolling_summary,
        state.recent_messages,
    )
    
    state.token_usage = token_estimate
    
    # ──────────────────────────────────────────────────────────────────
    # Stage 3: Compact if over budget (BEFORE agent runs)
    # ──────────────────────────────────────────────────────────────────
    if should_compact(token_estimate) and state.older_messages_ids:
        await emit_pipeline_event(
            PipelineEventType.COMPACTING_CONTEXT,
            session_id_str,
            {"messages_eligible": len(state.older_messages_ids)}
        )
        
        # Load the full older messages for compaction
        older_messages = await load_older_messages_for_compaction(
            session_id,
            state.older_messages_ids,
            db,
        )
        
        if older_messages:
            # Generate new summary (chaining previous if exists)
            new_summary = await compact_and_merge_summary(
                session_id=session_id,
                older_messages=older_messages,
                previous_summary=state.rolling_summary,
                db=db,
            )
            
            # Persist the new summary
            state.update_summary(new_summary, db)
            state.compaction_performed = True
            state.messages_compacted_count = len(older_messages)
            
            # Re-estimate after compaction
            token_estimate = estimate_tokens(
                state.rolling_summary,
                state.recent_messages,
            )
            state.token_usage = token_estimate
    
    # ──────────────────────────────────────────────────────────────────
    # Stage 4: Optional semantic retrieval (disabled by default)
    # ──────────────────────────────────────────────────────────────────
    semantic_messages = []
    
    if getattr(settings, "ENABLE_SEMANTIC_CHAT_RETRIEVAL", False):
        semantic_budget = (
            token_estimate["available"]
            - token_estimate["recent_tokens"]
            - token_estimate["summary_tokens"]
            - token_estimate["system_budget"]
        )
        
        if semantic_budget > 0 and state.older_messages_ids:
            # Load older messages for recency weighting in semantic search
            older_messages_for_ranking = await load_older_messages_for_compaction(
                session_id,
                state.older_messages_ids,
                db,
            )
            
            semantic_messages = await retrieve_semantic_messages(
                session_id_str=session_id_str,
                query=current_user_message,
                exclude_ids={},
                token_budget=semantic_budget,
                older_messages_db=older_messages_for_ranking,
            )
    
    # ──────────────────────────────────────────────────────────────────
    # Stage 5: Assemble final context
    # ──────────────────────────────────────────────────────────────────
    await emit_pipeline_event(PipelineEventType.ASSEMBLING_CONTEXT, session_id_str)
    
    final_context = assemble_context_window(
        summary=state.rolling_summary,
        recent_messages=state.recent_messages,
        semantic_messages=semantic_messages if semantic_messages else None,
    )
    
    # ──────────────────────────────────────────────────────────────────
    # Decision logging
    # ──────────────────────────────────────────────────────────────────
    summarize_decision = (
        "created" if state.compaction_performed
        else "reused" if state.rolling_summary
        else "none"
    )
    
    print(
        f"[ContextManager] session={session_id_str} | "
        f"msgs={len(final_context)} | "
        f"tokens≈{token_estimate['total']}/{token_estimate['available']} | "
        f"recent={len(state.recent_messages)} | "
        f"semantic={len(semantic_messages)} | "
        f"summary={summarize_decision} | "
        f"headroom={token_estimate['headroom']}"
    )
    
    return final_context
