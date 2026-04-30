"""
Pipeline orchestrator for document indexing.

Coordinates the complete indexing workflow:
1. Phase 1: Vector indexing (blocking, via asyncio.to_thread)
   - Creates Qdrant collection
   - Embeddings and stores vectors
   - Unblocks chat immediately (15-30 seconds)

2. Phase 2: Graph indexing (async, background)
   - Extracts entities and relationships
   - Builds Neo4j knowledge graph
   - Non-fatal errors (graph failure doesn't block vector success)

Status lifecycle:
- uploaded → indexing (upon start)
- indexing → indexed (when both phases complete successfully)
- indexing → indexed (if graph fails, vector alone = success)

Reuses split_docs from vector phase for graph phase (avoid double-loading).
"""

import asyncio
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import update

from app.db.database import SessionLocal
from app.models.source import Source, SourceStatus
from app.models.source_index import SourceIndex
from app.services.indexing.ingestion import (
    load_and_prepare_pdf,
    load_and_prepare_github,
    load_and_prepare_document,
)
from app.services.indexing.vector_index import (
    index_pdf_source,
    index_github_source,
    index_document_source,
    delete_qdrant_collection,
)
from app.services.indexing.graph_index import (
    build_pdf_graph,
    build_github_graph,
    delete_graph_by_source_id,
)
from app.utils.api_error import ApiError


async def run_indexing_pipeline(source_id: str) -> None:
    """
    Main async orchestrator for complete indexing pipeline.

    Two-phase approach:
    - Vector: Sync (via asyncio.to_thread), blocks chat until complete
    - Graph: Async background, unblocks immediately after vector completes

    Updates source status and source_index record progressively.
    Handles errors gracefully (graph failure is logged but non-fatal).

    Args:
        source_id: Source UUID as string

    Side Effects:
        - Updates Source.status to 'indexing' then 'indexed'
        - Updates SourceIndex with counts and timestamps
        - Creates Qdrant collections
        - Creates Neo4j entities and relationships
        - Logs errors to console (graph failures are non-fatal)

    Note: This function is meant to run in the background via BackgroundTasks.
    Exceptions are caught internally and logged.
    """
    db = None
    try:
        # ──────────────────────────────────────────────────────────────
        # Setup: Get DB session and source record
        # ──────────────────────────────────────────────────────────────
        db = SessionLocal()
        source = db.query(Source).filter(Source.id == source_id).first()

        if not source:
            print(f"[Pipeline] Source {source_id} not found")
            return

        print(f"[Pipeline] Starting indexing pipeline for source {source_id}")

        # Update status to indexing
        db.execute(
            update(Source).where(Source.id == source_id).values(status=SourceStatus.indexing)
        )
        db.commit()

        # ──────────────────────────────────────────────────────────────
        # Phase 1: Load and Prepare Documents
        # ──────────────────────────────────────────────────────────────
        try:
            effective_file_path = None

            if source.type.value == "pdf":
                # Check if this is a multi-format document (file_type stored in metadata)
                actual_file_type = source.source_metadata.get("file_type")
                local_path = source.source_metadata.get("file_path") or source.source_metadata.get("filename")
                file_url = source.source_metadata.get("file_url")

                if actual_file_type and actual_file_type not in ("pdf", ""):
                    loader_type = "document"
                    load_fn = lambda path: load_and_prepare_document(path, actual_file_type)
                else:
                    loader_type = "pdf"
                    load_fn = load_and_prepare_pdf

                last_error = None
                for candidate in (local_path, file_url):
                    if not candidate:
                        continue
                    try:
                        docs = await asyncio.to_thread(load_fn, candidate)
                        effective_file_path = candidate
                        break
                    except Exception as e:
                        last_error = e
                        if candidate == local_path and file_url:
                            print(
                                f"[Pipeline] Local load failed for source {source_id}, retrying via file_url"
                            )

                if not effective_file_path:
                    if last_error:
                        raise last_error
                    raise ApiError(400, "File path not found in metadata")

            elif source.type.value == "github":
                # For GitHub: extract repo details from metadata
                repo_url = source.source_metadata.get("repo_url")
                branch = source.source_metadata.get("branch", "main")
                include_ext = source.source_metadata.get("include_extensions") or []

                if not repo_url:
                    raise ApiError(400, "GitHub repo URL not found in metadata")

                access_token = None  # TODO: Get from user or env
                docs = await asyncio.to_thread(
                    load_and_prepare_github,
                    repo_url,
                    branch,
                    access_token,
                    include_ext,
                )
                loader_type = "github"

            else:
                raise ApiError(400, f"Unsupported source type: {source.type}")

            print(f"[Pipeline] Loaded {len(docs)} documents for source {source_id}")

        except Exception as e:
            print(f"[Pipeline] Failed to load documents for source {source_id}: {e}")
            db.execute(
                update(Source).where(Source.id == source_id).values(status=SourceStatus.failed)
            )
            db.commit()
            return

        # ──────────────────────────────────────────────────────────────
        # Phase 2: Vector Indexing (Blocking, via asyncio.to_thread)
        # ──────────────────────────────────────────────────────────────
        vector_result = None
        try:
            collection_name = f"src_{source_id}"

            if loader_type == "pdf":
                file_path = effective_file_path or source.source_metadata.get("file_url")
                vector_result = await asyncio.to_thread(
                    index_pdf_source, file_path, collection_name, source_id
                )

            elif loader_type == "document":
                # Multi-format document (docx, txt, md, etc.)
                file_path = effective_file_path or source.source_metadata.get("file_url")
                actual_file_type = source.source_metadata.get("file_type")
                vector_result = await asyncio.to_thread(
                    index_document_source,
                    file_path,
                    collection_name,
                    source_id,
                    actual_file_type,
                )
            
            else:  # github
                repo_url = source.source_metadata.get("repo_url")
                branch = source.source_metadata.get("branch", "main")
                include_ext = source.source_metadata.get("include_extensions") or []
                
                vector_result = await asyncio.to_thread(
                    index_github_source,
                    repo_url,
                    collection_name,
                    source_id,
                    branch,
                    include_ext,
                )

            print(
                f"[Pipeline] Vector indexing complete for source {source_id}: "
                f"{vector_result.get('vectors_added', 0)} vectors"
            )

            # Update SourceIndex with vector completion timestamp
            source_index = db.query(SourceIndex).filter(SourceIndex.source_id == source_id).first()
            if not source_index:
                source_index = SourceIndex(source_id=source_id)
                db.add(source_index)

            source_index.vector_indexed = True
            source_index.vector_indexed_at = datetime.utcnow()
            db.commit()

        except Exception as e:
            print(f"[Pipeline] Vector indexing failed for source {source_id}: {e}")
            db.execute(
                update(Source).where(Source.id == source_id).values(status=SourceStatus.failed)
            )
            db.commit()
            return  # Vector failure is fatal, don't proceed to graph

        # ──────────────────────────────────────────────────────────────
        # Mark as 'indexed' after vector completes (unblock chat)
        # ──────────────────────────────────────────────────────────────
        db.execute(
            update(Source).where(Source.id == source_id).values(status=SourceStatus.indexed)
        )
        db.commit()

        print(f"[Pipeline] Source {source_id} marked as indexed (vector complete, chat unblocked)")

        # ──────────────────────────────────────────────────────────────
        # Phase 3: Graph Indexing (Async Background, Non-Fatal)
        # ──────────────────────────────────────────────────────────────
        try:
            if loader_type == "pdf" or loader_type == "document":
                # Both PDF and multi-format documents use generic entity extraction
                graph_result = await build_pdf_graph(source_id, docs)
            else:  # github
                graph_result = await build_github_graph(source_id, docs)

            print(
                f"[Pipeline] Graph indexing complete for source {source_id}: "
                f"{graph_result.get('nodes_added', 0)} nodes, "
                f"{graph_result.get('relationships_added', 0)} relationships"
            )

            # Update SourceIndex with graph completion
            source_index = db.query(SourceIndex).filter(SourceIndex.source_id == source_id).first()
            if source_index:
                source_index.graph_indexed = True
                source_index.graph_indexed_at = datetime.utcnow()
                source_index.entity_count = graph_result.get("nodes_added", 0)
                source_index.relation_count = graph_result.get("relationships_added", 0)
                db.commit()

        except Exception as e:
            # Non-fatal: log error but don't block chat
            print(f"[Pipeline] Graph indexing failed for source {source_id} (non-fatal): {e}")
            # Continue without updating graph status

        print(f"[Pipeline] Pipeline complete for source {source_id}")

    except Exception as e:
        print(f"[Pipeline] Unexpected error in pipeline for source {source_id}: {e}")

    finally:
        if db:
            db.close()
