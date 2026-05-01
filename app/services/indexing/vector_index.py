"""
Vector indexing service for Qdrant.

This module only handles embeddings and storage. Document loading and
splitting MUST be performed by the ingestion layer. Callers should pass
the already split documents (`split_docs`) to `index_to_vector_store`.

Note: Functions here are SYNCHRONOUS — intended to be called via
`asyncio.to_thread` from the pipeline.
"""

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from app.core.config import settings
from app.utils.api_error import ApiError


# ─────────────────────────────────────────────────────────────────────────
# Client Initialization
# ─────────────────────────────────────────────────────────────────────────

def _get_qdrant_client() -> QdrantClient:
    """Get Qdrant client with configured credentials."""
    opts = {"url": settings.QDRANT_URL}
    if settings.QDRANT_API_KEY:
        opts["api_key"] = settings.QDRANT_API_KEY
    return QdrantClient(**opts)


def _get_embeddings() -> OpenAIEmbeddings:
    """Get OpenAI embeddings client."""
    return OpenAIEmbeddings(
        model=settings.OPENAI_EMBEDDING_MODEL,
        openai_api_key=settings.OPENAI_API_KEY,
    )


# ─────────────────────────────────────────────────────────────────────────
# Generic Vector Indexing
# ─────────────────────────────────────────────────────────────────────────

def index_to_vector_store(
    docs: list,
    collection_name: str,
    source_id: str,
    source_type: str,
) -> dict:
    """
    Generic vector indexing: attach metadata and store in Qdrant.

    Args:
        docs: List of LangChain Document objects (already split)
        collection_name: Qdrant collection name
        source_id: Source UUID (will be stringified)
        source_type: Type of source (pdf, github, etc.)

    Returns:
        Result dict with status, collection name, and chunk count

    Raises:
        ApiError: If indexing fails
    """
    if not docs:
        raise ApiError(400, "Documents array cannot be empty")

    try:
        # Stamp source metadata onto every chunk
        for doc in docs:
            # Ensure metadata exists and update
            meta = getattr(doc, "metadata", None)
            if meta is None:
                try:
                    doc.metadata = {}
                    meta = doc.metadata
                except Exception:
                    meta = {}

            meta.update({
                "source_id": str(source_id),
                "source_type": source_type,
            })

        # Index to Qdrant
        QdrantVectorStore.from_documents(
            documents=docs,
            embedding=_get_embeddings(),
            url=settings.QDRANT_URL,
            collection_name=collection_name,
            **{"api_key": settings.QDRANT_API_KEY} if settings.QDRANT_API_KEY else {},
        )

        chunks_indexed = len(docs)
        return {
            "status": "ok",
            "collection": collection_name,
            "chunks_indexed": chunks_indexed,
            "vectors_added": chunks_indexed,
        }

    except Exception as e:
        raise ApiError(500, f"Failed to index to Qdrant: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────
# Qdrant Collection Cleanup
# ─────────────────────────────────────────────────────────────────────────

def delete_qdrant_collection(collection_name: str) -> dict:
    """
    Delete a Qdrant collection.

    Args:
        collection_name: Collection name to delete

    Returns:
        Success result dict

    Raises:
        ApiError: If deletion fails
    """
    try:
        client = _get_qdrant_client()
        client.delete_collection(collection_name)
        return {"status": "ok", "collection": collection_name}
    except Exception as e:
        raise ApiError(500, f"Failed to delete Qdrant collection: {str(e)}")
