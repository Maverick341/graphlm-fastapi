"""
Vector indexing service for Qdrant.

Handles document embedding and storage in Qdrant vector database.
Returns split documents for reuse in graph indexing pipeline.

Note: Functions here are SYNCHRONOUS — called via asyncio.to_thread in pipeline.
"""

from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

from app.core.config import settings
from app.utils.api_error import ApiError
from .ingestion import load_and_prepare_pdf, load_and_prepare_github, load_and_prepare_document


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
        docs: List of LangChain Document objects (split)
        collection_name: Qdrant collection name
        source_id: Source UUID (will be stringified)
        source_type: Type of source (pdf, document, github)
    
    Returns:
        Result dict with status, collection name, and chunk count
    
    Raises:
        ApiError: If indexing fails
    """
    if not docs:
        raise ApiError(400, "Documents array cannot be empty")
    
    try:
        # ── Stamp source metadata onto every chunk ─────────────────
        for doc in docs:
            doc.metadata.update({
                "source_id": str(source_id),
                "source_type": source_type,
            })
        
        # ── Index to Qdrant ───────────────────────────────────────
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
# PDF Vector Indexing
# ─────────────────────────────────────────────────────────────────────────

def index_pdf_source(
    file_path: str,
    collection_name: str,
    source_id: str,
) -> dict:
    """
    Full PDF vector pipeline: load, split, and index.

    Returns split_docs so graph pipeline can reuse them (via nested return).

    Args:
        file_path: Path to PDF file (local or cloud URL)
        collection_name: Qdrant collection name
        source_id: Source UUID (as string)

    Returns:
        Result dict with status, vector metadata, and split_docs for graph reuse

    Raises:
        ApiError: If any step fails

    Note: This is a SYNC function called via asyncio.to_thread from pipeline.
    """
    try:
        # ── Load and split ────────────────────────────────────────
        split_docs = load_and_prepare_pdf(file_path)

        # ── Index to vector store ─────────────────────────────────
        vector_result = index_to_vector_store(
            split_docs,
            collection_name,
            source_id,
            "pdf",
        )

        return {
            "status": "ok",
            "vectors_added": vector_result["chunks_indexed"],
            "chunks_indexed": vector_result["chunks_indexed"],
            "split_docs": split_docs,  # ← Reused by graph pipeline
        }

    except ApiError:
        raise
    except Exception as e:
        raise ApiError(500, f"Failed to index PDF: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────
# Generic Document Vector Indexing (PDF, DOCX, TXT, MD)
# ─────────────────────────────────────────────────────────────────────────

def index_document_source(
    file_path: str,
    collection_name: str,
    source_id: str,
    file_type: str = None,
) -> dict:
    """
    Full document vector pipeline: load (PDF/DOCX/TXT/MD), split, and index.

    Returns split_docs so graph pipeline can reuse them.
    Auto-detects file type from extension if not provided.

    Args:
        file_path: Path to document file (local path)
        collection_name: Qdrant collection name
        source_id: Source UUID (as string)
        file_type: File type (pdf, docx, txt, md). If None, auto-detected.

    Returns:
        Result dict with status, vector metadata, and split_docs for graph reuse

    Raises:
        ApiError: If any step fails

    Note: This is a SYNC function called via asyncio.to_thread from pipeline.
    """
    try:
        # ── Load and split ────────────────────────────────────────
        split_docs = load_and_prepare_document(file_path, file_type)

        # Determine source type for metadata
        if not file_type:
            file_type = file_path.split(".")[-1].lower() if "." in file_path else "document"

        # ── Index to vector store ─────────────────────────────────
        vector_result = index_to_vector_store(
            split_docs,
            collection_name,
            source_id,
            file_type,
        )

        return {
            "status": "ok",
            "vectors_added": vector_result["chunks_indexed"],
            "chunks_indexed": vector_result["chunks_indexed"],
            "split_docs": split_docs,  # ← Reused by graph pipeline
        }

    except ApiError:
        raise
    except Exception as e:
        raise ApiError(500, f"Failed to index document: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────
# GitHub Vector Indexing
# ─────────────────────────────────────────────────────────────────────────

def index_github_source(
    repo_url: str,
    collection_name: str,
    source_id: str,
    branch: str = "main",
    include_extensions: list = None,
) -> dict:
    """
    Full GitHub vector pipeline: clone, load, split, and index.

    Returns split_docs so graph pipeline can reuse them.

    Args:
        repo_url: GitHub repository URL
        collection_name: Qdrant collection name
        source_id: Source UUID (as string)
        branch: Repository branch to index (default: "main")
        include_extensions: List of file extensions to include (None = all)

    Returns:
        Result dict with status, vector metadata, and split_docs for graph reuse

    Raises:
        ApiError: If any step fails

    Note: This is a SYNC function called via asyncio.to_thread from pipeline.
    """
    try:
        # ── Load and split ────────────────────────────────────────
        split_docs = load_and_prepare_github(
            repo_url,
            branch,
            access_token=None,  # TODO: Pass from config or parameter
            include_extensions=include_extensions or [],
        )

        # ── Index to vector store ─────────────────────────────────
        vector_result = index_to_vector_store(
            split_docs,
            collection_name,
            source_id,
            "github",
        )

        return {
            "status": "ok",
            "vectors_added": vector_result["chunks_indexed"],
            "chunks_indexed": vector_result["chunks_indexed"],
            "split_docs": split_docs,  # ← Reused by graph pipeline
        }

    except ApiError:
        raise
    except Exception as e:
        raise ApiError(500, f"Failed to index GitHub repository: {str(e)}")


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
