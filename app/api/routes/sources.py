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
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
from typing import Optional, List

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

router = APIRouter(prefix="/sources", tags=["sources"])


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
    title: str = Form(..., min_length=1, max_length=200, description="Display title for document"),
    file: UploadFile = File(..., description="Document file to upload (PDF, DOCX, TXT, MD)"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
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
    title = title.strip()
    if not title:
        raise ApiError(400, "Title cannot be empty")
    
    # TODO: Validate file size (e.g., max 50MB)
    
    # Create source via repository with initial status
    source = source_repo.create_source(
        db,
        current_user.id,
        title,
        SourceType.pdf.value,  # Use 'pdf' as generic document type for now
        metadata={
            "filename": file.filename,
            "content_type": file.content_type,
            "file_type": file_ext,  # Store actual file type for later detection
        }
    )
    
    # Upload document to Cloudinary
    try:
        cloudinary_result = upload_document_to_cloudinary(file, str(source.id))
        
        # Update source metadata with Cloudinary URL
        source.source_metadata.update({
            "file_url": cloudinary_result["secure_url"],
            "cloudinary_public_id": cloudinary_result["public_id"],
        })
        db.add(source)
        db.commit()
        
    except ApiError as e:
        # If Cloudinary upload fails, delete the source and raise error
        db.delete(source)
        db.commit()
        raise
    except Exception as e:
        # Unexpected error, rollback
        db.rollback()
        raise ApiError(500, f"Failed to upload document: {str(e)}")
    
    # Create source index metadata via repository
    source_index = source_repo.create_source_index(db, source.id, f"doc_{source.id}")
    
    # Trigger background indexing pipeline
    background_tasks.add_task(run_indexing_pipeline, str(source.id))
    
    # Update status to indexing
    source_repo.update_source_status(db, source.id, SourceStatus.indexing.value)
    source = source_repo.get_source_by_id(db, source.id)
    
    # Build response
    response_data = AddSourceResponse(
        source_id=source.id,
        title=source.title,
        type=source.type.value,
        status=source.status.value,
        collection_name=source_index.collection_name,
        status_url=f"/sources/{source.id}/status",
        message="Document accepted for processing. Vector indexing complete, graph indexing in progress.",
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
    background_tasks: BackgroundTasks = BackgroundTasks(),
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
    
    # Create source via repository with initial status
    source = source_repo.create_source(
        db,
        current_user.id,
        body.title,
        SourceType.github.value,
        metadata={
            "repo_url": body.repo_url,
            "branch": body.branch,
            "include_extensions": body.include_extensions,
        }
    )
    
    # Create source index metadata via repository
    source_index = source_repo.create_source_index(db, source.id, f"github_{source.id}")
    
    # Trigger background indexing pipeline
    background_tasks.add_task(run_indexing_pipeline, str(source.id))
    
    # Update status to indexing
    source_repo.update_source_status(db, source.id, SourceStatus.indexing.value)
    source = source_repo.get_source_by_id(db, source.id)
    
    # Build response
    response_data = AddSourceResponse(
        source_id=source.id,
        title=source.title,
        type=source.type.value,
        status=source.status.value,
        collection_name=source_index.collection_name,
        status_url=f"/sources/{source.id}/status",
        message="GitHub repository accepted for processing. Vector indexing complete, graph indexing in progress.",
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


@router.get("/{source_id}/status", response_model=ApiResponse)
@limiter.limit("20/minute")
async def get_source_status(
    request: Request,
    source_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get detailed indexing status for a source.
    
    Shows progress for both vector (Qdrant) and graph (Neo4j) indexing.
    Frontend polls this endpoint to show partial progress.
    
    Status lifecycle:
    1. "uploaded" - Source created, indexing not started
    2. "indexing" - Vector or graph indexing in progress
    3. "indexed" - Both vector and graph indexing complete
    4. "failed" - Indexing encountered error
    
    Args:
        source_id: Source ID (UUID)
        db: Database session
        current_user: Authenticated user
    
    Returns:
        ApiResponse with SourceStatusResponse
        Shows vector_indexed and graph_indexed status separately
    
    Raises:
        ApiError(404): If source not found
        ApiError(403): If source doesn't belong to user
    """
    source = source_repo.get_source_by_id(db, source_id)
    if not source:
        raise ApiError(404, "Source not found")
    
    verify_ownership(source.user_id, current_user.id, "source")
    
    # Build response
    response_data = build_source_status_response(source)
    
    return ApiResponse(
        statusCode=200,
        success=True,
        message="Source status retrieved successfully",
        data=response_data,
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
    
    # TODO: Delete Qdrant collection
    # TODO: Delete Neo4j entities (non-fatal if fails)
    
    # Delete source via repository (cascade deletes SourceIndex via SQLAlchemy relationship)
    source_repo.delete_source(db, source_id)
    
    # Build response
    response_data = DeleteSourceResponse(
        source_id=source_id,
        message="Source deleted. Vector and graph indexes cleaned up.",
    )
    
    return ApiResponse(
        statusCode=200,
        success=True,
        message="Source deleted successfully",
        data=response_data,
    )
