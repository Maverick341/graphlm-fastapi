"""
Document loading and preparation for indexing.

Handles multiple document types (PDF, DOCX, TXT, MD) and GitHub repositories.
Returns split documents with enriched metadata for both vector and graph pipelines.

Supports loading from both local file paths and Cloudinary URLs.
"""

from io import BytesIO
from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    TextLoader,
    GithubFileLoader,
)
from langchain_text_splitters import Language, RecursiveCharacterTextSplitter
from fastapi import UploadFile
import tempfile
import os
import requests
from urllib.parse import urlparse

from app.core.config import settings
from app.utils.api_error import ApiError

# ─────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────

SPLITTER_CONFIG = {
    "chunk_size": settings.CHUNK_SIZE,
    "chunk_overlap": settings.CHUNK_OVERLAP,
}

LARGE_FILE_THRESHOLD = 2000  # lines/content length

CODE_EXTENSIONS = {
    "js": "javascript",
    "ts": "typescript",
    "jsx": "javascript",
    "tsx": "typescript",
    "py": "python",
    "java": "java",
    "cpp": "cpp",
    "c": "c",
    "go": "go",
    "rs": "rust",
    "rb": "ruby",
    "php": "php",
    "cs": "csharp",
    "html": "html",
    "css": "css",
    "sql": "sql",
    "sh": "shell",
    "md": "markdown",
}

LANGUAGE_BY_EXT = {
    "c": Language.C,
    "cpp": Language.CPP,
    "cs": Language.CSHARP,
    "go": Language.GO,
    "html": Language.HTML,
    "java": Language.JAVA,
    "js": Language.JS,
    "jsx": Language.JS,
    "md": Language.MARKDOWN,
    "markdown": Language.MARKDOWN,
    "php": Language.PHP,
    "py": Language.PYTHON,
    "rb": Language.RUBY,
    "rs": Language.RUST,
    "ts": Language.TS,
    "tsx": Language.TS,
}

EXCLUDED_EXTENSIONS = {".json", ".lock", ".yml", ".yaml", ".gitignore", ".env"}


# ─────────────────────────────────────────────────────────────────────────
# URL Handling (Cloudinary)
# ─────────────────────────────────────────────────────────────────────────

def _download_file_from_url(url: str, file_ext: str) -> str:
    """
    Download a file from a URL and save to temporary file.
    
    Args:
        url: File URL (e.g., Cloudinary secure_url)
        file_ext: File extension (pdf, docx, txt, md)
    
    Returns:
        Path to temporary file
    
    Raises:
        ApiError: If download fails
    """
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Create temporary file with appropriate extension
        with tempfile.NamedTemporaryFile(suffix=f".{file_ext}", delete=False) as tmp:
            tmp.write(response.content)
            return tmp.name
    
    except Exception as e:
        raise ApiError(500, f"Failed to download file from URL: {str(e)}")


def _ensure_local_path(file_path: str, file_type: str) -> str:
    """
    Convert file path (URL or local) to local path.
    
    If file_path is a URL, downloads it to temp file.
    If file_path is local, returns as-is.
    
    Args:
        file_path: File path or URL
        file_type: File type (pdf, docx, txt, md)
    
    Returns:
        Local file path
    """
    if file_path.startswith("http://") or file_path.startswith("https://"):
        return _download_file_from_url(file_path, file_type)
    return file_path


# ─────────────────────────────────────────────────────────────────────────
# File Type Detection
# ─────────────────────────────────────────────────────────────────────────

def _get_file_type_from_filename(filename: str) -> str:
    """Extract file type from filename."""
    if not filename:
        return "unknown"
    ext = filename.split(".")[-1].lower()
    return ext if ext else "unknown"


def _normalize_github_repo(repo_url: str) -> str:
    """
    Normalize GitHub repo input to "owner/repo".

    Accepts full URLs (https://github.com/owner/repo) and SSH formats
    (git@github.com:owner/repo.git). If the input is already in
    owner/repo form, it is returned as-is.
    """
    if not repo_url:
        return repo_url

    cleaned = repo_url.strip()
    if cleaned.startswith("git@"):
        _, _, path = cleaned.partition(":")
    else:
        parsed = urlparse(cleaned)
        if parsed.scheme in ("http", "https"):
            path = parsed.path
        elif "github.com/" in cleaned:
            path = cleaned.split("github.com/", 1)[1]
        else:
            return cleaned

    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]

    parts = [part for part in path.split("/") if part]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return path or cleaned


def _get_github_repo_size_kb(repo_url: str, access_token: str | None) -> int | None:
    """Fetch repo size from GitHub API (size is in KB)."""
    if not repo_url or "/" not in repo_url:
        return None

    headers = {"Accept": "application/vnd.github+json"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"

    try:
        response = requests.get(
            f"https://api.github.com/repos/{repo_url}",
            headers=headers,
            timeout=10,
        )
        if response.status_code != 200:
            return None
        size_kb = response.json().get("size")
        return int(size_kb) if isinstance(size_kb, int) else None
    except Exception:
        return None


def _get_language_splitter(
    ext: str,
    chunk_size: int,
    chunk_overlap: int,
) -> RecursiveCharacterTextSplitter:
    language = LANGUAGE_BY_EXT.get(ext)
    if language:
        return RecursiveCharacterTextSplitter.from_language(
            language=language,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
    return RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


# ─────────────────────────────────────────────────────────────────────────
# Document Loaders (PDF, DOCX, TXT, MD)
# ─────────────────────────────────────────────────────────────────────────

def load_and_prepare_document(file_path: str, file_type: str = None) -> list:
    """
    Load and split a document (PDF, DOCX, TXT, MD) from local path or Cloudinary URL.
    
    Supports multiple formats and returns split chunks with enriched metadata.
    Auto-detects file type from extension if not provided.
    
    Args:
        file_path: Path to document file (local path or Cloudinary URL)
        file_type: File type (pdf, docx, txt, md). If None, detected from filename.
    
    Returns:
        List of split LangChain Document objects with metadata
    
    Raises:
        ApiError: If file type unsupported or loading fails
    """
    try:
        # Detect file type if not provided
        if not file_type:
            file_type = _get_file_type_from_filename(file_path).lower()
        
        # Ensure we have a local path (download from URL if needed)
        local_path = _ensure_local_path(file_path, file_type)
        
        try:
            # Route to appropriate loader
            if file_type == "pdf":
                loader = PyPDFLoader(local_path)
                
            elif file_type == "docx":
                loader = Docx2txtLoader(local_path)
                
            elif file_type in ("txt", "text", "md", "markdown"):
                loader = TextLoader(local_path, encoding="utf-8")
                
            else:
                raise ApiError(400, f"Unsupported file type: {file_type}. Supported: PDF, DOCX, TXT, MD")
            
            docs = loader.load()
            
            if not docs:
                raise ApiError(400, f"Failed to load {file_type.upper()} or file is empty")
            
            splitter = RecursiveCharacterTextSplitter(**SPLITTER_CONFIG)
            split_docs = splitter.split_documents(docs)
            
            if not split_docs:
                raise ApiError(400, f"Failed to split {file_type.upper()} documents")
            
            return split_docs
        
        finally:
            # Clean up temporary file if it was downloaded
            if file_path.startswith("http") and os.path.exists(local_path):
                try:
                    os.unlink(local_path)
                except Exception:
                    pass
    
    except ApiError:
        raise
    except Exception as e:
        raise ApiError(500, f"Failed to load and split document: {str(e)}")


# ─────────────────────────────────────────────────────────────────────────
# GitHub Loader with Enrichment
# ─────────────────────────────────────────────────────────────────────────

def load_and_prepare_github(
    repo_url: str,
    branch: str = "main",
    access_token: str = None,
    include_ext: list = None,
) -> list:
    """
    Load and split a GitHub repository with enriched metadata.
    
    Extracts code files and documentation, enriches with file type and language info.
    
    Args:
        repo_url: GitHub repo (e.g., "owner/repo")
        branch: Git branch name (default "main")
        access_token: GitHub access token (from settings if None)
        include_ext: List of file extensions to include (default: Python, JS, MD)
    
    Returns:
        List of split LangChain Document objects with enriched metadata
    
    Raises:
        ApiError: If repo URL invalid or loading fails
    """
    if not repo_url:
        raise ApiError(400, "Repository URL is required")

    repo_url = _normalize_github_repo(repo_url)
    
    if not access_token:
        access_token = settings.GITHUB_TOKEN
    
    if not access_token:
        raise ApiError(400, "GitHub access token is required")
    
    # Default extensions if not provided
    if not include_ext:
        include_ext = [".py", ".md", ".txt", ".js", ".ts", ".jsx", ".tsx"]
    
    try:
        # Create GitHub loader with file filtering
        loader = GithubFileLoader(
            repo=repo_url,
            branch=branch,
            access_token=access_token,
            github_api_url="https://api.github.com",
            file_filter=lambda path: (
                any(path.endswith(ext) for ext in include_ext)
                and not any(path.endswith(excluded) for excluded in EXCLUDED_EXTENSIONS)
            ),
        )
        
        docs = loader.load()
        
        if not docs:
            raise ApiError(400, "Failed to load GitHub repository or it is empty")
        
        # ── Enrich metadata ──────────────────────────────────────────
        enriched = []
        for doc in docs:
            file_path = doc.metadata.get("source", "")
            ext = file_path.split(".")[-1].lower() if "." in file_path else ""
            
            # Determine file type (code vs documentation)
            file_type = "markdown" if ext in ("md", "markdown", "txt") else "code"
            
            # Determine language
            language = CODE_EXTENSIONS.get(ext, ext or "unknown")
            
            doc.metadata.update({
                "file_type": file_type,
                "language": language,
                "path": file_path,
            })
            enriched.append(doc)
        
        repo_size_kb = _get_github_repo_size_kb(repo_url, access_token)
        is_large_repo = (
            repo_size_kb is not None
            and repo_size_kb >= settings.GITHUB_LARGE_REPO_SIZE_KB
        )

        # ── Smart splitting: large files split, small files kept whole ──
        large_chunk_size = int(settings.CHUNK_SIZE * 1.5)
        large_splitter = RecursiveCharacterTextSplitter(
            chunk_size=large_chunk_size,
            chunk_overlap=0,
        )
        split_docs = []
        
        for doc in enriched:
            if len(doc.page_content) < LARGE_FILE_THRESHOLD:
                # Small files: keep as-is
                split_docs.append(doc)
            else:
                # Large files: split with larger chunks
                if is_large_repo:
                    path = doc.metadata.get("path") or doc.metadata.get("source", "")
                    ext = path.split(".")[-1].lower() if "." in path else ""
                    splitter = _get_language_splitter(
                        ext=ext,
                        chunk_size=large_chunk_size,
                        chunk_overlap=0,
                    )
                    chunks = splitter.split_documents([doc])
                else:
                    chunks = large_splitter.split_documents([doc])
                split_docs.extend(chunks)
        
        if not split_docs:
            raise ApiError(400, "Failed to split GitHub repository documents")
        
        return split_docs
    
    except ApiError:
        raise
    except Exception as e:
        raise ApiError(500, f"Failed to load and split GitHub repository: {str(e)}")
