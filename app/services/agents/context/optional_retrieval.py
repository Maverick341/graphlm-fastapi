"""
Semantic retrieval over chat messages.

DISABLED BY DEFAULT.

This module is kept separate because:
  1. For most conversations, rolling summary + recent messages is sufficient
  2. Qdrant semantic search adds latency and complexity
  3. Source RAG (documents/GitHub) is more valuable than chat-message semantics
  4. Long-term memory (Mem0) handles persistent patterns
  5. Simpler architecture is easier to reason about

To enable semantic chat retrieval:
  Set ENABLE_SEMANTIC_CHAT_RETRIEVAL=true in .env
  The manager will then call retrieve_semantic_messages() after state loading

Otherwise, the system runs with summary + recent only, which is fast and clean.
"""

import asyncio
from typing import Optional

from app.core.config import settings

# Conditional import: only if explicitly enabled
_semantic_enabled = getattr(settings, "ENABLE_SEMANTIC_CHAT_RETRIEVAL", False)

if _semantic_enabled:
    import tiktoken
    from qdrant_client import QdrantClient
    from qdrant_client.http.models import Filter, FieldCondition, MatchValue
    from langchain_openai import OpenAIEmbeddings

    _qdrant = QdrantClient(url=settings.QDRANT_URL)
    _embeddings = OpenAIEmbeddings(
        model=settings.OPENAI_EMBEDDING_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
    )
    _tokenizer = tiktoken.get_encoding("cl100k_base")
    CHAT_MESSAGES_COLLECTION = "chat_messages"

    def _count_tokens(text: str) -> int:
        return len(_tokenizer.encode(text))

    def _count_messages_tokens(messages: list[dict]) -> int:
        total = 0
        for m in messages:
            total += _count_tokens(m.get("role", ""))
            total += _count_tokens(m.get("content", ""))
            total += 4
        return total

    async def retrieve_semantic_messages(
        session_id_str: str,
        query: str,
        exclude_ids: set[str],
        token_budget: int,
        older_messages_db: list,
    ) -> list[dict]:
        """
        Search the shared Qdrant collection for messages semantically related
        to the current query, scoped to this session.
        
        Re-ranks results by combining Qdrant similarity with recency weight:
          score = similarity * 0.7 + recency_weight * 0.3
        
        Args:
            session_id_str: Used in Qdrant payload filter (chat_id field)
            query: The current user message text (query vector source)
            exclude_ids: message_ids already in recent window (skip these)
            token_budget: Max tokens to spend on semantic results
            older_messages_db: DB records for recency weighting
        
        Returns:
            List of {role, content} dicts, re-ranked and budget-capped
        """
        try:
            # Build recency index: {message_id: normalized_position}
            total_older = len(older_messages_db)
            recency_index: dict[str, float] = {}
            for i, msg in enumerate(older_messages_db):
                recency_index[str(msg.id)] = i / max(total_older - 1, 1)

            # Embed query
            query_vector = await asyncio.to_thread(
                _embeddings.embed_query,
                query,
            )

            # Session-scoped filter
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="chat_id",
                        match=MatchValue(value=session_id_str),
                    )
                ]
            )

            # Raw Qdrant search
            results = await asyncio.to_thread(
                _qdrant.search,
                collection_name=CHAT_MESSAGES_COLLECTION,
                query_vector=query_vector,
                query_filter=query_filter,
                limit=settings.SEMANTIC_TOP_K,
                with_payload=True,
            )

            # ── Re-rank by similarity + recency ──────────────────────────
            scored: list[tuple[float, dict]] = []
            for point in results:
                payload = point.payload or {}
                message_id = payload.get("message_id", "")
                content = payload.get("content", "")
                role = payload.get("role", "user")

                if not content or message_id in exclude_ids:
                    continue

                similarity = point.score
                recency_w = recency_index.get(message_id, 0.0)
                combined_score = similarity * 0.7 + recency_w * 0.3

                scored.append((combined_score, {
                    "message_id": message_id,
                    "role": role,
                    "content": content,
                }))

            scored.sort(key=lambda x: x[0], reverse=True)

            # ── Budget cap + content dedup ──────────────────────────────
            semantic_msgs: list[dict] = []
            tokens_used = 0

            for _, candidate in scored:
                message_id = candidate["message_id"]
                content = candidate["content"]
                role = candidate["role"]

                # Skip if content already substantially represented
                if any(content in m["content"] for m in semantic_msgs):
                    continue

                msg_tokens = _count_tokens(content) + 4

                if tokens_used + msg_tokens > token_budget:
                    break

                semantic_msgs.append({
                    "role": role,
                    "content": f"[Related earlier context]\n{content}",
                })
                exclude_ids.add(message_id)
                tokens_used += msg_tokens

            return semantic_msgs

        except Exception as e:
            print(f"[Retrieval] Semantic search failed, skipping: {e}")
            return []

else:
    # Semantic search disabled: stub out the function
    async def retrieve_semantic_messages(
        session_id_str: str,
        query: str,
        exclude_ids: set[str],
        token_budget: int,
        older_messages_db: list,
    ) -> list[dict]:
        """Semantic search disabled — returns empty list."""
        return []
