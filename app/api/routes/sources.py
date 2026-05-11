"""
Source management routes for GraphLM FastAPI backend.

Endpoints for managing PDF and GitHub sources with unified interface.
Sources are indexed asynchronously for both vector (Qdrant) and graph (Neo4j).
All endpoints require authentication (current_user).
All endpoints return responses wrapped in ApiResponse.
"""

from fastapi import (
    APIRouter,
    Depends,
    Query,
    Request,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
)
from starlette.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
from typing import Optional, List
import asyncio
import json
import tempfile
import os
import shutil
from app.utils.logger import logger

from app.db.database import get_db
from app.models.user import User
from app.models.source import Source, SourceType, SourceStatus
from app.models.source_index import SourceIndex
from app.api.deps import get_current_user
from app.schemas.response import ApiResponse
from app.schemas.source import (
    AddGithubRequest,
    SourceResponse,
    SourceDetailResponse,
    SourceStatusResponse,
    AddSourceResponse,
    SourceListResponse,
    DeleteSourceResponse,
    SourceIndexStatus,
)
from app.utils.api_error import ApiError
from app.utils.db_queries import (
    verify_ownership,
    build_source_status_response,
)
from app.repositories import source_repo
from app.api.limiter import limiter
from app.services.indexing.pipeline import run_indexing_pipeline
from app.services.cloudinary_service import upload_document_to_cloudinary, delete_document_from_cloudinary
from app.services.indexing.vector_index import delete_qdrant_collection
from app.services.indexing.graph_index import delete_graph_by_source_id
from app.db.listeners.source_status_listener import source_status_listener

router = APIRouter(prefix="/sources", tags=["sources"])

# Terminal statuses — SSE stream closes automatically when reached
_TERMINAL_STATUSES = {"indexed", "failed"}


def _sse_event(event: str, data: dict) -> str:
    """
    Format a single Server-Sent Event frame.

    `default=str` handles UUID / datetime values that are not JSON-serialisable
    out of the box.  The client reads `event:` and `data:` fields.
    """
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# ─────────────────────────────────────────────────────────────────────────
# Source CRUD Endpoints
# ─────────────────────────────────────────────────────────────────────────

@router.post(
    "/upload",
    response_model=ApiResponse,
    status_code=202,
)
@limiter.limit("5/minute")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    title: str = Form(..., min_length=1, max_length=200, description="Display title for document"),
    file: UploadFile = File(..., description="Document file to upload (PDF, DOCX, TXT, MD)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload and index a document as a source.
    
    Supports multiple file types: PDF, DOCX, TXT, MD
    
    Performs async indexing:
    1. Save document file locally
    2. Create Source record with status="uploaded"
    3. Vector indexing (sync in background)
    4. Upload to Cloudinary (cloud storage)
    5. Graph indexing (async, non-blocking)
    6. Update Source.status to "indexed"
    
    Returns 202 Accepted with status polling URL.
    Frontend polls /sources/{id}/status to track progress.
    
    Args:
        request: FastAPI request (required for rate limiting)
        title: Display title for the document
        file: Uploaded document file (PDF, DOCX, TXT, or MD)
        background_tasks: FastAPI background tasks
        db: Database session
        current_user: Authenticated user
    
    Returns:
        ApiResponse with AddSourceResponse (202 Accepted)
        Includes status_url for polling progress
    
    Raises:
        ApiError(400): If file type is unsupported or title is invalid
        ApiError(400): If file size exceeds limit
    """
    # Validate file type
    if not file.filename:
        raise ApiError(400, "Filename is required")
    
    file_ext = file.filename.lower().split(".")[-1] if "." in file.filename else ""
    supported_types = {"pdf", "docx", "txt", "md", "text", "markdown"}
    
    if file_ext not in supported_types:
        raise ApiError(
            400,
            f"Unsupported file type: {file_ext}. Supported types: PDF, DOCX, TXT, MD, TEXT, MARKDOWN"
        )
    
    # Validate title
    if title:
        title = title.strip()
    
    if not title:
        title = file.filename
    
    # TODO: Validate file size (e.g., max 50MB)
    
    # Save uploaded file to temporary location (PRIMARY indexing source)
    temp_dir = tempfile.mkdtemp()
    temp_file_path = os.path.join(temp_dir, file.filename)
    
    try:
        with open(temp_file_path, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise ApiError(500, f"Failed to save file: {str(e)}")
    
    # Create source via repository with initial status
    source = source_repo.create_source(
        db,
        current_user.id,
        title,
        SourceType.document.value,
        metadata={
            "filename": file.filename,
            "content_type": file.content_type,
            "file_type": file_ext,
            "temp_file_path": temp_file_path,  # PRIMARY: local temp file
            "temp_dir": temp_dir,  # Directory to clean up later
        }
    )
    
    # Upload to Cloudinary as FALLBACK storage (optional, non-blocking)
    try:
        # Re-open temp file for Cloudinary upload (UploadFile already consumed)
        with open(temp_file_path, "rb") as f:
            # Create a simple object with .file attribute to match upload_document_to_cloudinary expectations
            class FileWrapper:
                def __init__(self, file_obj):
                    self.file = file_obj
            
            wrapped_file = FileWrapper(f)
            cloudinary_result = upload_document_to_cloudinary(wrapped_file, str(source.id))
            source.source_metadata = {
                **(source.source_metadata or {}),
                "cloudinary_url": cloudinary_result["secure_url"],  # FALLBACK
                "cloudinary_public_id": cloudinary_result["public_id"],
            }
            db.commit()
            db.refresh(source)
            logger.info(f"[Upload] Successfully uploaded to Cloudinary: {cloudinary_result['secure_url']}")
    except Exception as e:
        # Non-blocking: Cloudinary upload failure doesn't block indexing
        logger.warning(f"Cloudinary upload failed for source {source.id} (will use local temp file): {str(e)}")
    
    # Create source index metadata via repository
    source_index = source_repo.create_source_index(db, source.id, f"{SourceType.document.value}_{source.id}")
    
    # Update status to indexing
    source_repo.update_source_status(db, source.id, SourceStatus.indexing.value)
    
    # Trigger background indexing pipeline
    background_tasks.add_task(run_indexing_pipeline, str(source.id))

    source = source_repo.get_source_by_id(db, source.id)

    # Build response
    response_data = AddSourceResponse(
        source_id=source.id,
        title=source.title,
        type=source.type.value,
        status=source.status.value,
        collection_name=source_index.collection_name,
        file_url=source.source_metadata.get("cloudinary_url") if source.source_metadata else None,
        status_url=f"/sources/{source.id}/status",
        message="Document accepted for processing. Vector indexing will run; graph indexing runs in background. Poll status endpoint for progress.",
        created_at=source.created_at,
    )
    
    return ApiResponse(
        statusCode=202,
        success=True,
        message="Document uploaded successfully. Indexing started.",
        data=response_data,
    )


@router.post(
    "/github",
    response_model=ApiResponse,
    status_code=202,
)
@limiter.limit("5/minute")
async def add_github(
    request: Request,
    body: AddGithubRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Add a GitHub repository as a source for indexing.
    
    Repository is cloned and indexed for both vector and graph retrieval.
    
    Performs async indexing:
    1. Create Source record with status="uploaded"
    2. Clone repository
    3. Vector indexing (chunk files → embed → Qdrant)
    4. Graph indexing (extract entities/relations → Neo4j)
    5. Update Source.status to "indexed"
    
    Returns 202 Accepted with status polling URL.
    Frontend polls /sources/{id}/status to track progress.
    
    Args:
        request: FastAPI request (required for rate limiting)
        body: AddGithubRequest with repo_url, branch, title
        background_tasks: FastAPI background tasks
        db: Database session
        current_user: Authenticated user
    
    Returns:
        ApiResponse with AddSourceResponse (202 Accepted)
        Includes status_url for polling progress
    
    Raises:
        ApiError(400): If repo_url is invalid or doesn't contain 'github.com'
    """
    # Validate repo URL contains github.com
    if 'github.com' not in body.repo_url.lower():
        raise ApiError(400, "Repository URL must be a valid GitHub URL")
    
    title = body.title
    if not title:
        url_parts = body.repo_url.rstrip('/').split('/')
        title = url_parts[-1] if url_parts else "GitHub Repository"
        if title.endswith('.git'):
            title = title[:-4]
    
    # Create source via repository with initial status
    source = source_repo.create_source(
        db,
        current_user.id,
        title,
        SourceType.github.value,
        metadata={
            "repo_url": body.repo_url,
            "branch": body.branch,
            "include_extensions": body.include_extensions or [],
        }
    )
    
    # Create source index metadata via repository
    source_index = source_repo.create_source_index(db, source.id, f"{SourceType.github.value}_{source.id}")
    
    # Update status to indexing
    source_repo.update_source_status(db, source.id, SourceStatus.indexing.value)

    # Trigger background indexing pipeline
    background_tasks.add_task(run_indexing_pipeline, str(source.id))
    
    source = source_repo.get_source_by_id(db, source.id)
    
    # Build response
    response_data = AddSourceResponse(
        source_id=source.id,
        title=source.title,
        type=source.type.value,
        status=source.status.value,
        collection_name=source_index.collection_name,
        status_url=f"/sources/{source.id}/status",
        message="Repository accepted for processing. Vector indexing will run; graph indexing runs in background. Poll status endpoint for progress.",
        created_at=source.created_at,
    )
    
    return ApiResponse(
        statusCode=202,
        success=True,
        message="GitHub repository added successfully. Indexing started.",
        data=response_data,
    )


@router.get("/", response_model=ApiResponse)
@limiter.limit("20/minute")
async def list_sources(
    request: Request,
    skip: int = Query(0, ge=0, description="Number of sources to skip"),
    limit: int = Query(10, ge=1, le=100, description="Maximum sources per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    List all sources for the authenticated user.
    
    Includes both PDF and GitHub sources.
    Ordered by creation date (newest first).
    Supports pagination.
    
    Args:
        skip: Number of sources to skip (default 0)
        limit: Maximum sources per page (default 10, max 100)
        db: Database session
        current_user: Authenticated user
    
    Returns:
        ApiResponse with SourceListResponse (paginated)
    
    Status: 200 OK
    """
    # Get paginated sources via repository (newest first)
    sources, total = source_repo.get_sources_by_user(db, current_user.id, skip, limit)
    
    # Build response
    sources_data = [SourceResponse.model_validate(source) for source in sources]
    total_pages = (total + limit - 1) // limit  # Ceiling division
    
    response_data = SourceListResponse(
        items=sources_data,
        skip=skip,
        limit=limit,
        total=total,
        pages=total_pages,
        has_more=(skip + limit) < total,
    )
    
    return ApiResponse(
        statusCode=200,
        success=True,
        message="Sources retrieved successfully",
        data=response_data,
    )


@router.get("/{source_id}", response_model=ApiResponse)
@limiter.limit("20/minute")
async def get_source(
    request: Request,
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get detailed information about a specific source.
    
    Includes type-specific metadata (PDF or GitHub).
    
    Args:
        source_id: Source ID (UUID)
        db: Database session
        current_user: Authenticated user
    
    Returns:
        ApiResponse with SourceDetailResponse
    
    Raises:
        ApiError(404): If source not found
        ApiError(403): If source doesn't belong to user
    """
    source = source_repo.get_source_by_id(db, source_id)
    if not source:
        raise ApiError(404, "Source not found")
    
    verify_ownership(source.user_id, current_user.id, "source")
    
    # Build response
    response_data = SourceDetailResponse(
        id=source.id,
        user_id=source.user_id,
        title=source.title,
        type=source.type.value,
        status=source.status.value,
        metadata=source.source_metadata,
        created_at=source.created_at,
    )
    
    return ApiResponse(
        statusCode=200,
        success=True,
        message="Source retrieved successfully",
        data=response_data,
    )


@router.get(
    "/{source_id}/status",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {
                "text/event-stream": {
                    "schema": {
                        "type": "string",
                        "description": "SSE stream containing real-time JSON event frames."
                    }
                }
            },
            "description": "Stream of real-time indexing progress updates (snapshot, source_status_changed, source_index_changed, complete).",
        },
        401: {"description": "Unauthorized — missing or invalid credentials."},
        403: {"description": "Forbidden — user does not own the source."},
        404: {"description": "Not Found — source not found."},
    },
)
@limiter.limit("10/minute")
async def get_source_status(
    request: Request,
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Stream real-time indexing status for a source via Server-Sent Events (SSE).

    The connection stays open until:
      * **The client closes it** (browser tab close, `EventSource.close()`).
      * **The source reaches a terminal state**: `"indexed"` or `"failed"`.

    ### Event types emitted:
    * `snapshot`              — Immediate first event: current DB state.
    * `source_status_changed` — Fired when sources.status column changes.
    * `source_index_changed`  — Fired when vector/graph indexed flags change.
    * `complete`              — Final event before the stream closes.

    Heartbeat comments (`: heartbeat`) are sent every 20 s to prevent proxies and load balancers from closing idle connections.

    ### Frontend Usage (JavaScript):
    ```javascript
    const es = new EventSource(`/sources/${id}/status`, { withCredentials: true });
    
    es.addEventListener("snapshot", (e) => {
        console.log("Initial snapshot:", JSON.parse(e.data));
    });
    
    es.addEventListener("source_status_changed", (e) => {
        console.log("Overall status updated:", JSON.parse(e.data));
    });
    
    es.addEventListener("source_index_changed", (e) => {
        console.log("Index progress updated:", JSON.parse(e.data));
    });
    
    es.addEventListener("complete", (e) => {
        console.log("Indexing complete, closing SSE:", JSON.parse(e.data));
        es.close();
    });
    
    es.onerror = (err) => {
        console.error("SSE error occurred:", err);
        es.close();
    };
    ```

    Args:
        source_id:    Source UUID.
        db:           SQLAlchemy session (used only for initial snapshot).
        current_user: Authenticated user.

    Returns:
        StreamingResponse (text/event-stream) — stays alive until terminal state.

    Raises:
        ApiError(404): Source not found.
        ApiError(403): Source does not belong to current user.
    """
    # --- Auth + ownership (runs synchronously before streaming begins) ---
    source = source_repo.get_source_by_id(db, source_id)
    if not source:
        raise ApiError(404, "Source not found")

    verify_ownership(source.user_id, current_user.id, "source")

    # Snapshot the current state so the client gets immediate feedback
    initial_status: SourceStatusResponse = build_source_status_response(source)
    source_id_str = str(source_id)

    async def event_generator():
        # 1. Always emit the current DB snapshot first
        yield _sse_event("snapshot", initial_status.model_dump())

        # 2. If already in a terminal state AND graph is also resolved, close immediately.
        # If overall_status is already "indexed" but graph is still pending (graph.indexed is
        # False and no error_message yet), we must stay open to receive the graph NOTIFY.
        already_failed = initial_status.overall_status == "failed"
        already_indexed = initial_status.overall_status == "indexed"
        graph_already_resolved = (
            initial_status.graph.indexed is True
            or initial_status.error_message is not None
        )

        if already_failed or (already_indexed and graph_already_resolved):
            yield _sse_event(
                "complete",
                {
                    "message": "Indexing already complete.",
                    "overall_status": initial_status.overall_status,
                },
            )
            return

        # 3. Register a personal queue with the global PG NOTIFY listener.
        #    Two-condition state machine: we close only when BOTH are true:
        #      a) overall_status has reached "indexed" or "failed"  (sources trigger)
        #      b) graph indexing has resolved — success OR error     (source_indexes trigger)
        #
        #    Pipeline order that caused the original bug:
        #      vector_indexed=True  → source_index_changed (graph still False)
        #      status="indexed"     → source_status_changed ← OLD code closed here ❌
        #      graph_indexed=True   → source_index_changed  ← frontend never saw this
        #
        #    With the state machine the stream stays alive until the graph event arrives.
        queue = source_status_listener.subscribe(source_id_str)
        # Seed from snapshot: if status is already "indexed" when the client connects,
        # the source_status_changed NOTIFY already fired before subscription — it will
        # never arrive again. Pre-set the flag so the state machine only waits for the
        # graph_resolved condition.
        reached_indexed_status: bool = already_indexed
        graph_resolved: bool = False           # set when graph_indexed=True or error_message set
        try:
            while True:
                # Check whether the HTTP client has gone away
                if await request.is_disconnected():
                    logger.info("[SSE] Client disconnected for source %s", source_id_str)
                    break

                # Wait for the next notification with a heartbeat timeout
                try:
                    data: dict = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    # Send a comment line — keeps proxies alive, invisible to client
                    yield ": heartbeat\n\n"
                    continue

                # Emit the notification payload as an SSE event
                event_type: str = data.get("event", "update")
                yield _sse_event(event_type, data)

                # ── Update state machine ──────────────────────────────────

                if event_type == "source_status_changed":
                    overall = data.get("overall_status")

                    # Hard-fail: close immediately, graph is moot
                    if overall == "failed":
                        yield _sse_event("complete", {"overall_status": "failed"})
                        break

                    if overall == "indexed":
                        reached_indexed_status = True

                elif event_type == "source_index_changed":
                    # Graph is resolved when it either succeeded or recorded an error
                    if (
                        data.get("graph_indexed") is True
                        or data.get("error_message") is not None
                    ):
                        graph_resolved = True

                # ── Close only when BOTH conditions are satisfied ─────────
                if reached_indexed_status and graph_resolved:
                    yield _sse_event(
                        "complete",
                        {"overall_status": "indexed", "graph_resolved": graph_resolved},
                    )
                    break
        finally:
            # Always clean up — even on abrupt client disconnect
            source_status_listener.unsubscribe(source_id_str, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            # Tells Nginx not to buffer this response — critical for SSE
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/{source_id}", response_model=ApiResponse)
@limiter.limit("5/minute")
async def delete_source(
    request: Request,
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a source and clean up all associated indexes.
    
    Cascade cleanup:
    1. Delete Qdrant collection (vector index)
    2. Delete Neo4j entities and relationships (graph index)
    3. Delete SourceIndex metadata
    4. Delete Source record
    
    If graph cleanup fails, deletion still succeeds (non-fatal).
    
    Args:
        source_id: Source ID (UUID)
        db: Database session
        current_user: Authenticated user
    
    Returns:
        ApiResponse with DeleteSourceResponse
    
    Raises:
        ApiError(404): If source not found
        ApiError(403): If source doesn't belong to user
    """
    source = source_repo.get_source_by_id(db, source_id)
    if not source:
        raise ApiError(404, "Source not found")
    
    verify_ownership(source.user_id, current_user.id, "source")
    
    source_type_value = source.type.value if source.type else "unknown"

    # Clean up Cloudinary backup if it exists (optional, non-blocking)
    try:
        cloudinary_public_id = source.source_metadata.get("cloudinary_public_id") if source.source_metadata else None
        if cloudinary_public_id:
            delete_document_from_cloudinary(cloudinary_public_id)
            logger.info(f"[Delete] Cleaned up Cloudinary file for source {source_id}")
    except Exception as e:
        logger.warning(f"Failed to delete Cloudinary backup for source {source_id}: {str(e)}")
    
    
    # Delete from Qdrant (vector index)
    qdrant_deletion_status = None
    qdrant_error = None
    try:
        qdrant_deletion_status = delete_qdrant_collection(f"{source_type_value}_{source_id}")
    except Exception as e:
        qdrant_error = str(e)
        qdrant_deletion_status = {"status": "error", "collection": f"{source_type_value}_{source_id}", "error": qdrant_error}
    
    # Delete from Neo4j (graph index)
    neo4j_deletion_status = None
    neo4j_error = None
    try:
        neo4j_deletion_status = await delete_graph_by_source_id(str(source_id))
    except Exception as e:
        neo4j_error = str(e)
        neo4j_deletion_status = {"status": "error", "source_id": str(source_id), "error": neo4j_error}
   
    # Check for deletion failures and raise error if any occurred
    qdrant_success = qdrant_deletion_status and qdrant_deletion_status.get("status") == "ok"
    neo4j_success = neo4j_deletion_status and neo4j_deletion_status.get("status") == "ok"
    
    if not (qdrant_success and neo4j_success):
        errors = []
        if not qdrant_success:
            errors.append({"index": "qdrant", "error": qdrant_error or "Unknown error"})
        if not neo4j_success:
            errors.append({"index": "neo4j", "error": neo4j_error or "Unknown error"})
        
        raise ApiError(
            500,
            f"Failed to clean up indexes for source {source_id}",
            code="INDEX_CLEANUP_FAILED",
            errors=errors
        )
    
    # Database cascade will handle join table cleanup
    # Delete source via repository (cascade deletes SourceIndex via SQLAlchemy relationship)
    source_repo.delete_source(db, source_id)
    
    # Build response (success case only)
    response_data = DeleteSourceResponse(
        source_id=source_id,
        message="Source deleted. Vector and graph indexes cleaned up.",
        qdrant_deletion_status=qdrant_deletion_status,
        neo4j_deletion_status=neo4j_deletion_status,
    )
    
    return ApiResponse(
        statusCode=200,
        success=True,
        message="Source deleted successfully",
        data=response_data,
    )
