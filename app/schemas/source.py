"""
Source schemas for PDF and GitHub source management.

Includes request validation schemas and response schemas for unified source handling.
"""

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime


# ─────────────────────────────────────────────────────────────────────────
# REQUEST SCHEMAS (Input validation)
# ─────────────────────────────────────────────────────────────────────────

class AddGithubRequest(BaseModel):
    """
    Add GitHub repository as source for indexing.
    
    Repository is cloned and indexed for both vector and graph retrieval.
    """
    title: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Display title for this source"
    )
    repo_url: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="GitHub repository URL (e.g., 'https://github.com/owner/repo' or 'owner/repo')"
    )
    branch: str = Field(
        default="main",
        min_length=1,
        max_length=100,
        description="Repository branch to index (default: 'main')"
    )
    include_extensions: Optional[List[str]] = Field(
        default=None,
        description="File extensions to include (e.g., ['.py', '.md', '.txt']). None = include all"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "title": "GraphLM Repository",
                "repo_url": "https://github.com/owner/graphlm",
                "branch": "main",
                "include_extensions": [".py", ".md", ".txt"]
            }
        }


# ─────────────────────────────────────────────────────────────────────────
# RESPONSE SCHEMAS (Output serialization)
# ─────────────────────────────────────────────────────────────────────────

class SourceResponse(BaseModel):
    """
    Basic source information for list endpoints.
    
    Minimal metadata without indexing status details.
    """
    id: UUID = Field(description="Source ID")
    user_id: UUID = Field(description="Owner user ID")
    title: str = Field(description="Source title")
    type: str = Field(
        description="Source type: 'pdf' or 'github'"
    )
    status: str = Field(
        description="Indexing status: 'uploaded', 'indexing', 'indexed', or 'failed'"
    )
    created_at: datetime = Field(description="Source creation timestamp")

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "323e4567-e89b-12d3-a456-426614174002",
                "user_id": "223e4567-e89b-12d3-a456-426614174001",
                "title": "architecture.pdf",
                "type": "pdf",
                "status": "indexed",
                "created_at": "2026-04-30T10:25:00Z"
            }
        }


class PdfMetadata(BaseModel):
    """
    PDF-specific metadata.
    """
    file_url: Optional[str] = Field(
        default=None,
        description="Cloudinary URL for PDF file"
    )
    local_path: Optional[str] = Field(
        default=None,
        description="Local file path (may be deleted after indexing)"
    )
    file_size_bytes: Optional[int] = Field(
        default=None,
        description="PDF file size in bytes"
    )

    class Config:
        from_attributes = True


class GithubMetadata(BaseModel):
    """
    GitHub-specific metadata.
    """
    repo_url: str = Field(description="GitHub repository URL")
    branch: str = Field(description="Indexed branch")
    clone_url: Optional[str] = Field(
        default=None,
        description="HTTPS clone URL"
    )
    file_count: Optional[int] = Field(
        default=None,
        description="Number of files indexed"
    )

    class Config:
        from_attributes = True


class SourceDetailResponse(BaseModel):
    """
    Full source information with metadata.
    
    Returned by GET /sources/{id} endpoint.
    Includes type-specific metadata (PDF or GitHub).
    """
    id: UUID = Field(description="Source ID")
    user_id: UUID = Field(description="Owner user ID")
    title: str = Field(description="Source title")
    type: str = Field(description="Source type: 'pdf' or 'github'")
    status: str = Field(description="Indexing status")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Type-specific metadata (pdf or github)",
        validation_alias="source_metadata"
    )
    created_at: datetime = Field(description="Creation timestamp")
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Last update timestamp"
    )

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "323e4567-e89b-12d3-a456-426614174002",
                "user_id": "223e4567-e89b-12d3-a456-426614174001",
                "title": "architecture.pdf",
                "type": "pdf",
                "status": "indexed",
                "metadata": {
                    "file_url": "https://cloudinary.com/.../architecture.pdf",
                    "file_size_bytes": 2048576
                },
                "created_at": "2026-04-30T10:25:00Z",
                "updated_at": "2026-04-30T10:30:00Z"
            }
        }


class SourceIndexStatus(BaseModel):
    """
    Individual indexing pipeline status.
    """
    indexed: bool = Field(description="Whether indexing is complete")
    indexed_at: Optional[datetime] = Field(
        default=None,
        description="Completion timestamp"
    )
    entity_count: Optional[int] = Field(
        default=None,
        description="Number of entities (graph indexing)"
    )
    relation_count: Optional[int] = Field(
        default=None,
        description="Number of relationships (graph indexing)"
    )


class SourceStatusResponse(BaseModel):
    """
    Detailed indexing status for source.
    
    Returned by GET /sources/{id}/status endpoint.
    Shows progress for both vector and graph indexing pipelines.
    Frontend polls this to track indexing progress.
    """
    source_id: UUID = Field(description="Source ID")
    title: str = Field(description="Source title")
    type: str = Field(description="Source type")
    overall_status: str = Field(
        description="Overall status: 'uploaded', 'indexing', 'indexed', or 'failed'"
    )
    vector: SourceIndexStatus = Field(
        description="Vector indexing (Qdrant) status"
    )
    graph: SourceIndexStatus = Field(
        description="Graph indexing (Neo4j) status"
    )
    collection_name: Optional[str] = Field(
        default=None,
        description="Qdrant collection name for vector index"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if status is 'failed'"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "source_id": "323e4567-e89b-12d3-a456-426614174002",
                "title": "architecture.pdf",
                "type": "pdf",
                "overall_status": "indexed",
                "vector": {
                    "indexed": True,
                    "indexed_at": "2026-04-30T10:28:00Z"
                },
                "graph": {
                    "indexed": True,
                    "indexed_at": "2026-04-30T10:30:00Z",
                    "entity_count": 45,
                    "relation_count": 78
                },
                "collection_name": "pdf_323e4567e89b12d3a456426614174002",
                "error_message": None
            }
        }


class AddSourceResponse(BaseModel):
    """
    Response when adding a new source (PDF or GitHub).
    
    Returned with 202 Accepted status for async processing.
    Includes status URL for polling progress.
    """
    source_id: UUID = Field(description="Newly created source ID")
    title: str = Field(description="Source title")
    type: str = Field(description="Source type")
    status: str = Field(description="Initial status (typically 'indexing')")
    collection_name: Optional[str] = Field(
        default=None,
        description="Qdrant collection name for this source"
    )
    status_url: str = Field(
        description="URL to poll for indexing progress"
    )
    message: str = Field(
        description="Human-readable status message"
    )
    created_at: datetime = Field(description="Creation timestamp")

    class Config:
        json_schema_extra = {
            "example": {
                "source_id": "323e4567-e89b-12d3-a456-426614174002",
                "title": "architecture.pdf",
                "type": "pdf",
                "status": "indexing",
                "collection_name": "pdf_323e4567e89b12d3a456426614174002",
                "status_url": "/api/v1/sources/323e4567-e89b-12d3-a456-426614174002/status",
                "message": "PDF accepted for processing. Vector indexing complete, graph indexing in progress.",
                "created_at": "2026-04-30T10:25:00Z"
            }
        }


class SourceListResponse(BaseModel):
    """
    Paginated sources list response.
    
    Returned by GET /sources endpoint.
    """
    items: List[SourceResponse] = Field(description="Sources for current page")
    skip: int = Field(description="Number of items skipped")
    limit: int = Field(description="Items per page")
    total: int = Field(description="Total sources available")
    pages: int = Field(description="Total number of pages")
    has_more: bool = Field(description="Whether more items exist")

    class Config:
        json_schema_extra = {
            "example": {
                "items": [
                    {
                        "id": "323e4567-e89b-12d3-a456-426614174002",
                        "user_id": "223e4567-e89b-12d3-a456-426614174001",
                        "title": "architecture.pdf",
                        "type": "pdf",
                        "status": "indexed",
                        "created_at": "2026-04-30T10:25:00Z"
                    }
                ],
                "skip": 0,
                "limit": 10,
                "total": 1,
                "pages": 1,
                "has_more": False
            }
        }


class DeleteSourceResponse(BaseModel):
    """
    Response after deleting a source.
    
    Confirms deletion and cleanup of indexes.
    """
    source_id: UUID = Field(description="Deleted source ID")
    message: str = Field(description="Confirmation message")

    class Config:
        json_schema_extra = {
            "example": {
                "source_id": "323e4567-e89b-12d3-a456-426614174002",
                "message": "Source deleted. Vector and graph indexes cleaned up."
            }
        }
