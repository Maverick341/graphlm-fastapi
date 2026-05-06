import asyncio
import openai
import tiktoken
from uuid import UUID

from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    VectorParams,
    Filter,
    FieldCondition,
    MatchValue,
)
from sqlalchemy.orm import Session as DBSession

from app.core.config import settings
from app.models.chat_message import ChatMessage, MessageRole


"""
Claude-style context window builder for the RAG agent.

Three-layer context window (assembled in this order):
  [summary]           ← compressed history of older messages (if exists)
  [semantic_messages] ← older messages relevant to current query (Qdrant)
  [recent_messages]   ← last KEEP_RECENT messages verbatim (always included)

Flow per request:
  1. Fetch ALL messages from DB for this session
  2. Fetch existing summary (if any) from DB
  3. Split: older_messages = all[:-KEEP_RECENT], recent = all[-KEEP_RECENT:]
  4. Estimate total tokens: summary + recent + system_prompt_budget
  5. If total > AVAILABLE_CONTEXT → summarize(older_messages), persist/update
  6. Semantic search older messages in Qdrant (session-filtered, budget-capped)
  7. Assemble: [summary] + [semantic] + [recent]

Qdrant — shared collection:
  All session messages share ONE collection: "chat_messages"
  Every point carries `chat_id` in payload for session-scoped filtering.
  This avoids Qdrant collection-per-session proliferation.

Token budgeting — dynamic from settings:
  MAX_CONTEXT          = MODEL_MAX_TOKENS * CONTEXT_SAFE_RATIO
  AVAILABLE_CONTEXT    = MAX_CONTEXT - RESERVED_FOR_RAG - RESERVED_FOR_RESPONSE
  Summarization fires when: summary_tokens + recent_tokens + system_budget > AVAILABLE_CONTEXT

Summarization:
  Only older_messages are summarized — recent_messages are NEVER touched.
  Summary is stored as a ChatMessage (role=system, content="[SUMMARY]...")
  On subsequent requests the existing summary is fetched instead of re-generating.
  When new summarization is needed, the OLD summary is updated in-place (no duplicates).
"""


# ─────────────────────────────────────────────────────────────────────────
# Shared Qdrant collection for all session message history
# ─────────────────────────────────────────────────────────────────────────

CHAT_MESSAGES_COLLECTION = "chat_messages"

# Module-level flag — collection is created once per process lifetime.
# Avoids calling _qdrant.get_collections() on every embed_message call.
_collection_checked: bool = False


# ─────────────────────────────────────────────────────────────────────────
# Clients (module-level singletons)
# ─────────────────────────────────────────────────────────────────────────

_qdrant = QdrantClient(
    url=settings.QDRANT_URL,
    # api_key=settings.QDRANT_API_KEY,
)

_embeddings = OpenAIEmbeddings(
    model=settings.OPENAI_EMBEDDING_MODEL,
    openai_api_key=settings.OPENAI_API_KEY,
)

_openai = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

_tokenizer = tiktoken.get_encoding("cl100k_base")


# ─────────────────────────────────────────────────────────────────────────
# Dynamic token budget (derived from settings — no hardcoded values)
# ─────────────────────────────────────────────────────────────────────────

# System prompt overhead (tool descriptions + session context injected into agent).
# Configurable so it can be tuned as the prompt grows with new tools.
# Falls back to 1_000 if not set, matching the previous implicit assumption.
_SYSTEM_PROMPT_BUDGET: int = getattr(settings, "SYSTEM_PROMPT_BUDGET", 1_000)

def _get_available_context() -> int:
    """
    Compute available token budget for context window at call time.
    Reading from settings means changes to env vars take effect on restart
    without code changes.
    """
    max_context = int(settings.MODEL_MAX_TOKENS * settings.CONTEXT_SAFE_RATIO)
    return (
        max_context
        - settings.CONTEXT_RESERVED_FOR_RAG
        - settings.CONTEXT_RESERVED_FOR_RESPONSE
    )


# ─────────────────────────────────────────────────────────────────────────
# Token counting
# ─────────────────────────────────────────────────────────────────────────

def _count_tokens(text: str) -> int:
    """Accurate token count via tiktoken (cl100k_base — works for all OpenAI models)."""
    return len(_tokenizer.encode(text))


def _count_messages_tokens(messages: list[dict]) -> int:
    """
    Sum token count across all messages.
    Adds 4 tokens per message for OpenAI role/content separator overhead.
    """
    total = 0
    for m in messages:
        total += _count_tokens(m.get("role", ""))
        total += _count_tokens(m.get("content", ""))
        total += 4  # per-message overhead
    return total


# ─────────────────────────────────────────────────────────────────────────
# Qdrant collection management
# ─────────────────────────────────────────────────────────────────────────

def _ensure_collection() -> None:
    """
    Create the shared chat_messages Qdrant collection if it doesn't exist.
    text-embedding-3-small produces 1536-dimensional vectors.

    Uses a module-level boolean flag so the existence check runs exactly once
    per process lifetime — not once per embed call. Safe for async use because
    Python's GIL makes the boolean read/write atomic.
    """
    global _collection_checked
    if _collection_checked:
        return

    existing = [c.name for c in _qdrant.get_collections().collections]
    if CHAT_MESSAGES_COLLECTION not in existing:
        _qdrant.create_collection(
            collection_name=CHAT_MESSAGES_COLLECTION,
            vectors_config=VectorParams(
                size=1536,
                distance=Distance.COSINE,
            ),
        )

    _collection_checked = True


# ─────────────────────────────────────────────────────────────────────────
# Message embedding — called as background task after each turn
# ─────────────────────────────────────────────────────────────────────────

async def embed_message(
    session_id: str,
    message_id: str,
    role: str,
    content: str,
) -> None:
    """
    Embed a single message into the shared chat_messages Qdrant collection.

    Uses message_id as the Qdrant point ID (deterministic → idempotent re-runs).
    Payload carries chat_id for session-scoped filtering on retrieval.

    Short messages (below MIN_EMBED_CHARS) are skipped — they carry no
    semantic signal worth retrieving ("ok", "thanks", etc.)

    Non-fatal: failures are logged, the message remains in PostgreSQL.
    DO NOT pass a DB session here — this runs as a FastAPI BackgroundTask
    that outlives the request. It creates no DB writes (is_embedded flag
    was removed from the model patch to avoid a stale-session write).

    Args:
        session_id:  UUID string of the chat session (used as chat_id payload)
        message_id:  UUID string of the ChatMessage record (used as Qdrant point ID)
        role:        "user" or "assistant"
        content:     The message text to embed
    """
    if len(content) < settings.MIN_EMBED_CHARS:
        return  # too short to be semantically useful

    # Skip trivially short assistant replies ("Sure.", "Got it.", etc.) —
    # they carry no semantic signal worth retrieving in future turns.
    if role == "assistant" and len(content) < 50:
        return

    try:
        _ensure_collection()

        doc = Document(
            page_content=content,
            metadata={
                "message_id": message_id,
                "chat_id":    session_id,   # ← session filter key
                "role":       role,
                "content":    content,      # stored for reconstruction on retrieval
            },
        )

        vector_store = QdrantVectorStore(
            client=_qdrant,
            collection_name=CHAT_MESSAGES_COLLECTION,
            embedding=_embeddings,
        )

        await asyncio.to_thread(
            vector_store.add_documents,
            [doc],
            ids=[message_id],  # deterministic ID → no duplicate points on retry
        )

    except Exception as e:
        print(f"[Context] embed_message failed for {message_id}: {e}")
        # Non-fatal — PostgreSQL is source of truth, Qdrant is search index only


# ─────────────────────────────────────────────────────────────────────────
# Summarization
# ─────────────────────────────────────────────────────────────────────────

async def _call_summarizer(messages: list[dict]) -> str:
    """
    Call OpenAI to produce a compact bullet-point summary of a message list.
    Returns text prefixed with [SUMMARY] for easy identification in DB queries.

    temperature=0 for deterministic, stable output across retries.
    """
    conversation_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages
    )

    response = await _openai.chat.completions.create(
        model=settings.OPENAI_LLM_MODEL,
        max_tokens=600,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a conversation summarizer. "
                    "Summarize the conversation below into a concise bullet-point list "
                    "of key facts, decisions, preferences, and topics. "
                    "Preserve all technical details, entity names, and specifics. "
                    "Output only the bullet list — no preamble."
                ),
            },
            {
                "role": "user",
                "content": f"Conversation to summarize:\n\n{conversation_text}",
            },
        ],
    )

    return "[SUMMARY]\n" + response.choices[0].message.content


async def _get_or_update_summary(
    session_id: UUID,
    older_messages: list[dict],
    db: DBSession,
    existing_summary_record: ChatMessage | None,
) -> str:
    """
    Create or update the rolling summary for this session.

    Fix (Issue 1): When a summary already exists, it is prepended to older_messages
    before calling the summarizer — so the new summary inherits all previously
    compressed knowledge. This gives a rolling chain:
        summary_v1 → summary_v2 → summary_v3

    Without this fix, each new summary would only cover the current older_messages
    slice, discarding everything that was previously compressed.

    The existing summary record is updated in-place — no duplicate rows.

    Args:
        session_id:              Chat session UUID
        older_messages:          The current older_messages slice (dicts)
        db:                      SQLAlchemy session
        existing_summary_record: ORM record if a summary row already exists

    Returns:
        New summary text string (prefixed with [SUMMARY])
    """
    # ── Fix 1: Chain previous summary into the input ──────────────────────
    # Prepend the old summary as a system message so the new summary
    # covers old compressed knowledge + new older_messages together.
    if existing_summary_record:
        messages_to_summarize = [
            {"role": "system", "content": existing_summary_record.content}
        ] + older_messages
    else:
        messages_to_summarize = older_messages

    summary_text = await _call_summarizer(messages_to_summarize)

    if existing_summary_record:
        # Update in-place → no duplicate summary rows ever
        existing_summary_record.content = summary_text
        db.commit()
    else:
        db.add(ChatMessage(
            chat_id=session_id,
            role=MessageRole.system,
            content=summary_text,
        ))
        db.commit()

    return summary_text


# ─────────────────────────────────────────────────────────────────────────
# Semantic retrieval from Qdrant
# ─────────────────────────────────────────────────────────────────────────

async def _semantic_search(
    session_id_str: str,
    query: str,
    exclude_ids: set[str],
    token_budget: int,
    older_messages_db: list,
) -> list[dict]:
    """
    Search the shared Qdrant collection for messages semantically related
    to the current query, scoped to this session.

    Fix (Issue 3): Before appending a result, check if its content is already
    substantially represented in accumulated semantic_msgs. This prevents
    near-duplicate messages (same topic, slightly different wording) from
    padding the context with repetition.

    Fix (Issue 5): Re-rank results by combining Qdrant similarity score with
    a recency weight. Recent messages from the older_messages slice are more
    likely to be relevant than very old ones with similar embeddings.
    Score = similarity * 0.7 + recency_weight * 0.3
    recency_weight is the normalized position of the message in older_messages
    (0.0 = oldest, 1.0 = most recent in the older slice).

    Ranking: after re-scoring, results are sorted descending before budget cap.
    No score threshold — budget is the only hard gate.

    Args:
        session_id_str:    Used in the Qdrant payload filter (chat_id field)
        query:             The current user message text (query vector source)
        exclude_ids:       message_ids already in the recent window (skip these)
        token_budget:      Max tokens to spend on semantic results
        older_messages_db: DB records for the older slice (used for recency index)

    Returns:
        List of {role, content} dicts, re-ranked and budget-capped.
    """
    try:
        # Build a position index for recency weighting
        # {message_id_str: normalized_position}  where 1.0 = most recent in older slice
        total_older = len(older_messages_db)
        recency_index: dict[str, float] = {}
        for i, msg in enumerate(older_messages_db):
            # i=0 is oldest → weight 0.0; i=total-1 is most recent → weight 1.0
            recency_index[str(msg.id)] = i / max(total_older - 1, 1)

        # Embed the query vector
        query_vector = await asyncio.to_thread(
            _embeddings.embed_query,
            query,
        )

        # Session-scoped filter — MUST match chat_id in point payload
        query_filter = Filter(
            must=[
                FieldCondition(
                    key="chat_id",
                    match=MatchValue(value=session_id_str),
                )
            ]
        )

        # Raw Qdrant search — not via LangChain wrapper, so filter param works
        results = await asyncio.to_thread(
            _qdrant.search,
            collection_name=CHAT_MESSAGES_COLLECTION,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=settings.SEMANTIC_TOP_K,
            with_payload=True,
        )

        # ── Fix 5: Re-rank by similarity + recency ────────────────────────
        scored: list[tuple[float, dict]] = []
        for point in results:
            payload    = point.payload or {}
            message_id = payload.get("message_id", "")
            content    = payload.get("content", "")
            role       = payload.get("role", "user")

            if not content or message_id in exclude_ids:
                continue

            similarity    = point.score  # Qdrant cosine score [0, 1]
            recency_w     = recency_index.get(message_id, 0.0)
            combined_score = similarity * 0.7 + recency_w * 0.3

            scored.append((combined_score, {
                "message_id": message_id,
                "role":       role,
                "content":    content,
            }))

        # Sort by combined score descending — best first
        scored.sort(key=lambda x: x[0], reverse=True)

        # ── Budget cap + Fix 3: content dedup ─────────────────────────────
        semantic_msgs: list[dict] = []
        tokens_used = 0

        for _, candidate in scored:
            message_id = candidate["message_id"]
            content    = candidate["content"]
            role       = candidate["role"]

            # Fix 3: skip if this content is substantially already represented.
            # Simple substring check on the raw content (before label prefix).
            # Catches near-duplicate messages from similar turns.
            if any(content in m["content"] for m in semantic_msgs):
                continue

            msg_tokens = _count_tokens(content) + 4  # +4 per-message overhead

            if tokens_used + msg_tokens > token_budget:
                break  # budget exhausted — remaining candidates are lower-scored

            semantic_msgs.append({
                "role":    role,
                "content": f"[Related earlier context]\n{content}",
            })
            exclude_ids.add(message_id)
            tokens_used += msg_tokens

        return semantic_msgs

    except Exception as e:
        print(f"[Context] Semantic search failed, skipping: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────
# Main: build_context_window
# ─────────────────────────────────────────────────────────────────────────

async def build_context_window(
    session_id: UUID,
    current_user_message: str,
    db: DBSession,
) -> list[dict]:
    """
    Build the full context window for the agent.

    Returns [{role, content}, ...] in chronological order, ready to pass
    directly to the OpenAI Agents SDK Runner.

    Final structure (top → bottom = oldest → newest context):
    ┌─────────────────────────────────────────────────────────────────┐
    │  {"role": "system", "content": "[SUMMARY]..."}  (if exists)    │
    │  {"role": ..., "content": "[Related earlier context]\n..."}     │
    │   ... more semantic results ...                                  │
    │  {"role": "user",      "content": "..."}  ← recent verbatim    │
    │  {"role": "assistant", "content": "..."}                        │
    │   ... last KEEP_RECENT messages ...                              │
    └─────────────────────────────────────────────────────────────────┘

    Args:
        session_id:           Chat session UUID
        current_user_message: The user's current message (used as semantic query)
        db:                   SQLAlchemy session

    Returns:
        List of message dicts for the agent
    """
    session_id_str   = str(session_id)
    available_budget = _get_available_context()

    # ── Step 1: Fetch ALL real messages from DB ───────────────────────────
    # Exclude system-role summary records — those are fetched separately.
    all_messages_db = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.chat_id == session_id,
            ChatMessage.role.in_([MessageRole.user, MessageRole.assistant]),
        )
        .order_by(ChatMessage.created_at.asc())  # chronological
        .all()
    )

    # ── Step 2: Fetch existing summary (if any) ───────────────────────────
    existing_summary_record = (
        db.query(ChatMessage)
        .filter(
            ChatMessage.chat_id == session_id,
            ChatMessage.role == MessageRole.system,
            ChatMessage.content.like("[SUMMARY]%"),
        )
        .order_by(ChatMessage.created_at.desc())
        .first()
    )

    existing_summary_text: str | None = (
        existing_summary_record.content if existing_summary_record else None
    )

    # ── Step 3: Split older / recent ─────────────────────────────────────
    keep_recent = settings.CONTEXT_KEEP_RECENT

    if len(all_messages_db) <= keep_recent:
        # Not enough messages to split — everything is "recent"
        older_messages_db = []
        recent_messages_db = all_messages_db
    else:
        older_messages_db  = all_messages_db[:-keep_recent]
        recent_messages_db = all_messages_db[-keep_recent:]

    recent_msgs = [
        {"role": msg.role.value, "content": msg.content}
        for msg in recent_messages_db
    ]

    older_msgs = [
        {"role": msg.role.value, "content": msg.content}
        for msg in older_messages_db
    ]

    # ── Step 4: Token estimation ──────────────────────────────────────────
    recent_tokens  = _count_messages_tokens(recent_msgs)
    summary_tokens = _count_tokens(existing_summary_text) if existing_summary_text else 0
    total_estimated = summary_tokens + recent_tokens + _SYSTEM_PROMPT_BUDGET

    # ── Step 5: Summarize older messages if over budget ───────────────────
    summary_msg: dict | None = None

    if older_msgs:
        if total_estimated > available_budget:
            # Budget exceeded — (re)generate summary.
            # Fix 1: pass the ORM record so _get_or_update_summary can chain
            # the old summary into the new one (v1 → v2 → v3 rolling chain).
            summary_text = await _get_or_update_summary(
                session_id,
                older_msgs,
                db,
                existing_summary_record,   # ← Fix 1: pass record, not just text
            )
            summary_msg = {"role": "system", "content": summary_text}
        elif existing_summary_text:
            # Budget is fine but a summary exists — keep reusing it.
            summary_msg = {"role": "system", "content": existing_summary_text}

    # ── Step 6: Semantic retrieval from Qdrant ────────────────────────────
    current_summary_tokens = (
        _count_tokens(summary_msg["content"]) if summary_msg else 0
    )
    semantic_budget = (
        available_budget
        - recent_tokens
        - current_summary_tokens
        - _SYSTEM_PROMPT_BUDGET
    )

    recent_ids = {str(msg.id) for msg in recent_messages_db}

    semantic_msgs: list[dict] = []
    if semantic_budget > 0 and older_messages_db:
        semantic_msgs = await _semantic_search(
            session_id_str=session_id_str,
            query=current_user_message,
            exclude_ids=recent_ids,
            token_budget=semantic_budget,
            older_messages_db=older_messages_db,  # ← Fix 5: for recency weighting
        )

    # ── Step 7: Assemble final context window ─────────────────────────────
    final_context: list[dict] = []

    if summary_msg:
        final_context.append(summary_msg)

    final_context.extend(semantic_msgs)
    final_context.extend(recent_msgs)

    # ── Fix 2: Hard token guard ───────────────────────────────────────────
    # Rare edge case: if the assembled window still exceeds budget (e.g. the
    # summary itself is very large, or recent messages are unusually long),
    # trim semantic messages one by one from the end (lowest-scored last)
    # until we're within budget. recent_msgs are NEVER trimmed.
    total_tokens = _count_messages_tokens(final_context)

    if total_tokens > available_budget and semantic_msgs:
        print(
            f"[Context] Hard guard triggered: {total_tokens} > {available_budget}. "
            f"Trimming {len(semantic_msgs)} semantic message(s)."
        )
        while semantic_msgs and total_tokens > available_budget:
            semantic_msgs.pop()  # remove lowest-scored (appended last by _semantic_search)
            final_context = (
                ([summary_msg] if summary_msg else [])
                + semantic_msgs
                + recent_msgs
            )
            total_tokens = _count_messages_tokens(final_context)

    # ── Decision logging ──────────────────────────────────────────────────
    summarize_decision = (
        "updated"  if older_msgs and total_estimated > available_budget
        else "reused" if summary_msg
        else "none"
    )
    print(
        f"[Context] session={session_id_str} | "
        f"total_msgs={len(final_context)} | tokens≈{total_tokens}/{available_budget} | "
        f"recent={len(recent_msgs)} | semantic={len(semantic_msgs)} | "
        f"summary={summarize_decision} | "
        f"budget_headroom={available_budget - total_tokens}"
    )

    return final_context