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
import shutil
import os

from app.db.database import SessionLocal
from app.models.source import Source, SourceStatus
from app.models.source_index import SourceIndex
from app.services.indexing.ingestion import (
    load_and_prepare_document,
    load_and_prepare_github,
)
from app.services.indexing.vector_index import index_to_vector_store, delete_qdrant_collection
from app.services.indexing.graph_index import (
    build_pdf_graph,
    build_github_graph,
    delete_graph_by_source_id,
)
from app.utils.api_error import ApiError
from app.repositories import source_repo


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
        # Phase 1: Load and Prepare Documents (ONLY PLACE)
        # ──────────────────────────────────────────────────────────────
        try:
            if source.type.value == "document":
                file_type = source.source_metadata.get("file_type")
                
                # PRIMARY: Try temp file first
                temp_file_path = source.source_metadata.get("temp_file_path")
                file_path = None
                
                if temp_file_path and os.path.exists(temp_file_path):
                    file_path = temp_file_path
                    print(f"[Pipeline] Using temp file for source {source_id}: {temp_file_path}")
                # FALLBACK: Use Cloudinary URL if temp file missing
                elif source.source_metadata.get("cloudinary_url"):
                    file_path = source.source_metadata.get("cloudinary_url")
                    print(f"[Pipeline] Temp file missing, falling back to Cloudinary for source {source_id}")
                else:
                    raise ApiError(400, "No file path or Cloudinary URL found in source metadata")
                
                if not file_type:
                    raise ApiError(400, "File type not found in source metadata")
                
                try:
                    docs = await asyncio.to_thread(
                        load_and_prepare_document,
                        file_path,
                        file_type,
                    )
                except Exception as e:
                    # If temp file failed and we have Cloudinary as backup
                    if temp_file_path and source.source_metadata.get("cloudinary_url"):
                        print(f"[Pipeline] Temp file failed ({str(e)}), retrying with Cloudinary fallback")
                        try:
                            docs = await asyncio.to_thread(
                                load_and_prepare_document,
                                source.source_metadata.get("cloudinary_url"),
                                file_type,
                            )
                        except Exception as e2:
                            raise ApiError(500, f"Both temp file and Cloudinary failed: {str(e2)}")
                    else:
                        raise

            elif source.type.value == "github":
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

            else:
                raise ApiError(400, f"Unsupported source type: {source.type.value}")

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

            # Vector indexing operates on already split docs (from ingestion)
            vector_result = await asyncio.to_thread(
                index_to_vector_store,
                docs,
                collection_name,
                source_id,
                source.type.value if hasattr(source, "type") else loader_type,
            )

            print(
                f"[Pipeline] Vector indexing complete for source {source_id}: "
                f"{vector_result.get('vectors_added', 0)} vectors"
            )

            # Update SourceIndex with vector completion using repo helper
            updated = source_repo.set_vector_indexed(db, source_id, True)
            if not updated:
                raise ApiError(500, "SourceIndex missing for source")

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
            if source.type.value == "github":
                result = await build_github_graph(source_id, docs)
            else:
                result = await build_pdf_graph(source_id, docs)

            print(
                f"[Pipeline] Graph indexing complete for source {source_id}: "
                f"{result.get('nodes_added', 0)} nodes, "
                f"{result.get('relationships_added', 0)} relationships"
            )

            # Update SourceIndex with graph completion using repo helper
            source_repo.set_graph_indexed(
                db,
                source_id,
                True,
                entity_count=result.get('nodes_added', 0),
                relation_count=result.get('relationships_added', 0),
            )

        except Exception as e:
            # Non-fatal: log error but don't block chat
            print(f"[Pipeline] Graph indexing failed for source {source_id} (non-fatal): {e}")
            # Record graph failure information on SourceIndex for frontend visibility
            try:
                source_repo.set_graph_indexed(
                    db,
                    source_id,
                    False,
                    entity_count=0,
                    relation_count=0,
                    error_message=str(e),
                )
            except Exception as e2:
                print(f"[Pipeline] Failed to record graph error for source {source_id}: {e2}")

        print(f"[Pipeline] Pipeline complete for source {source_id}")

    except Exception as e:
        print(f"[Pipeline] Unexpected error in pipeline for source {source_id}: {e}")

    finally:
        # Cleanup temporary files
        try:
            temp_dir = source.source_metadata.get("temp_dir") if source else None
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
                print(f"[Pipeline] Cleaned up temporary directory for source {source_id}")
        except Exception as e:
            print(f"[Pipeline] Error cleaning up temp files for source {source_id}: {e}")
        
        if db:
            db.close()
