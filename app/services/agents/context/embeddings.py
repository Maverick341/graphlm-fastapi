"""
Message embedding into Qdrant vector store.

Handles embedding messages into the shared "chat_messages" Qdrant collection.
Called as a background task after each turn (zero latency to user).

Non-fatal: Embedding failures don't affect the user experience.
PostgreSQL remains the source of truth.
"""

import asyncio
from langchain_openai import OpenAIEmbeddings
from langchain_core.documents import Document
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.http.models import Distance, VectorParams

from app.core.config import settings

# ─────────────────────────────────────────────────────────────────────────
# Shared Qdrant collection for all session message history
# ─────────────────────────────────────────────────────────────────────────

CHAT_MESSAGES_COLLECTION = "chat_messages"

# Module-level flag: collection is created once per process lifetime.
# Avoids calling _qdrant.get_collections() on every embed_message call.
_collection_checked: bool = False


# ─────────────────────────────────────────────────────────────────────────
# Clients (module-level singletons)
# ─────────────────────────────────────────────────────────────────────────

_qdrant = QdrantClient(
    url=settings.QDRANT_URL,
    # api_key=settings.QDRANT_API_KEY,  # uncomment if using API key auth
)

_embeddings = OpenAIEmbeddings(
    model=settings.OPENAI_EMBEDDING_MODEL,
    openai_api_key=settings.OPENAI_API_KEY,
)


# ─────────────────────────────────────────────────────────────────────────
# Collection management
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
                size=1536,  # text-embedding-3-small dimension
                distance=Distance.COSINE,
            ),
        )

    _collection_checked = True


# ─────────────────────────────────────────────────────────────────────────
# Message embedding
# ─────────────────────────────────────────────────────────────────────────

async def embed_message(
    session_id: str,
    message_id: str,
    role: str,
    content: str,
) -> None:
    """
    Embed a single message into the shared chat_messages Qdrant collection.
    
    Called as a FastAPI BackgroundTask from the route, AFTER:
      - assistant reply is saved to DB
      - response is returned to the user
    
    This means embedding adds ZERO latency to the user's experience.
    
    Uses message_id as the Qdrant point ID (deterministic → idempotent).
    Payload carries chat_id for session-scoped filtering on retrieval.
    
    Short messages (below MIN_EMBED_CHARS) are skipped — they carry no
    semantic signal worth retrieving ("ok", "thanks", etc.)
    
    Non-fatal: failures are logged, the message remains in PostgreSQL.
    
    Args:
        session_id: UUID string of the chat session (stored as chat_id payload)
        message_id: UUID string of the ChatMessage record (Qdrant point ID)
        role: "user" or "assistant"
        content: The message text to embed
    """
    if len(content) < settings.MIN_EMBED_CHARS:
        return  # too short to be semantically useful

    # Skip trivially short assistant replies
    if role == "assistant" and len(content) < 50:
        return

    try:
        _ensure_collection()

        doc = Document(
            page_content=content,
            metadata={
                "message_id": message_id,
                "chat_id": session_id,  # session filter key
                "role": role,
                "content": content,  # stored for reconstruction on retrieval
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
        print(f"[Embeddings] embed_message failed for {message_id}: {e}")
        # Non-fatal — PostgreSQL is source of truth, Qdrant is search index only
