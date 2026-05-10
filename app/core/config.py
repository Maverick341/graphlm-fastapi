from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

# Load .env into os.environ FIRST — ensures third-party libraries
# (OpenAI Agents SDK, langchain, mem0, etc.) that read env vars
# directly can find them. pydantic-settings reads .env too, but
# only into its own Settings object, not into os.environ.
_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path, override=False)  # override=False: real env vars take priority

class Settings(BaseSettings):
    # Database Configuration
    DATABASE_URL: str

    # Async DSN for asyncpg-based services (e.g. PG LISTEN/NOTIFY listener).
    # asyncpg requires plain `postgresql://` — no SQLAlchemy driver prefix.
    # If not set explicitly in .env, it is auto-derived from DATABASE_URL.
    ASYNC_DATABASE_URL: str = ""

    @model_validator(mode="after")
    def _derive_async_url(self) -> "Settings":
        """Auto-derive ASYNC_DATABASE_URL from DATABASE_URL when not set."""
        if not self.ASYNC_DATABASE_URL:
            # Strip SQLAlchemy driver suffix: postgresql+psycopg2:// → postgresql://
            url = self.DATABASE_URL
            if "+" in url.split("://")[0]:
                scheme, rest = url.split("://", 1)
                plain_scheme = scheme.split("+")[0]  # e.g. "postgresql"
                url = f"{plain_scheme}://{rest}"
            self.ASYNC_DATABASE_URL = url
        return self

    # JWT Configuration - Access Token
    ACCESS_TOKEN_SECRET: str
    ACCESS_TOKEN_EXPIRE_HOURS: int = 15

    # JWT Configuration - Refresh Token
    REFRESH_TOKEN_SECRET: str
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Application Configuration
    PORT: int = 4000
    ENVIRONMENT: str = "development"  # development, testing, production
    DEBUG: bool = False
    BASE_URL: str = "http://localhost:4000"
    CLIENT_URL: str = "http://localhost:5173"

    # Email Configuration (SMTP)
    MAILTRAP_SMTP_HOST: str = "smtp.mailtrap.io"
    MAILTRAP_SMTP_PORT: int = 2525
    MAILTRAP_SMTP_USER: str = ""
    MAILTRAP_SMTP_PASS: str = ""
    MAILTRAP_SENDEREMAIL: str = "noreply@example.com"
    MAIL_FROM_NAME: str = "GraphLM Team"

    # Cloudinary Configuration
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    # GitHub OAuth Configuration
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_REDIRECT_URI: str = ""

    # File Upload Configuration
    MAX_AVATAR_FILE_SIZE: int = 1_048_576  # 1MB in bytes
    ALLOWED_IMAGE_TYPES: list = ["image/jpeg", "image/png", "image/webp", "image/gif"]

    # Indexing Configuration - Qdrant (Vector DB)
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""

    # Indexing Configuration - Neo4j (Graph DB)
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USERNAME: str = "neo4j"
    NEO4J_PASSWORD: str = ""

    # Indexing Configuration - OpenAI (LLM & Embeddings)
    OPENAI_API_KEY: str = ""
    OPENAI_LLM_MODEL: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Indexing Configuration - GitHub
    GITHUB_PERSONAL_ACCESS_TOKEN: str = ""
    GITHUB_LARGE_REPO_SIZE_KB: int = 50_000

    # Indexing Configuration - Chunking & Concurrency
    CHUNK_SIZE: int = 1000
    CHUNK_OVERLAP: int = 200
    INDEXING_CONCURRENCY: int = 3
    MAX_DOCUMENT_SIZE_MB: int = 50

    MODEL_MAX_TOKENS: int = 120000          # adjust per model (gpt-4o = 128K)
    CONTEXT_SAFE_RATIO: float = 0.75         # use 75% of model max
    CONTEXT_RESERVED_FOR_RAG: int = 15000  # headroom for vector/graph retrieval results
    CONTEXT_RESERVED_FOR_RESPONSE: int = 5000  # headroom for agent reply
    CONTEXT_KEEP_RECENT: int = 6            # always include last N messages verbatim
    SEMANTIC_TOP_K: int = 15               # Qdrant candidates for semantic retrieval
    MIN_EMBED_CHARS: int = 20              # skip embedding messages shorter than this
    SYSTEM_PROMPT_BUDGET: int = 1_000      # token headroom for agent system prompt + tool descriptions
    COMPACTION_THRESHOLD: float = 0.85      # trigger compaction at this % of available budget
    COMPACTION_TARGET_RATIO: float = 0.50   # after compaction, reduce usage to this % of budget

    MEM0_API_KEY: str = ""

    ENABLE_SEMANTIC_CHAT_RETRIEVAL: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        validate_default=True
    )


settings = Settings()

# ─────────────────────────────────────────────────────────────────────────
# Neo4j driver — module-level lazy singleton
# Pydantic BaseSettings doesn't support mutable @property state reliably.
# ─────────────────────────────────────────────────────────────────────────
_neo4j_driver_instance = None


def get_neo4j_driver():
    """Return (and lazily create) the shared AsyncGraphDatabase driver."""
    from neo4j import AsyncGraphDatabase

    global _neo4j_driver_instance
    if _neo4j_driver_instance is None:
        _neo4j_driver_instance = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USERNAME, settings.NEO4J_PASSWORD),
        )
    return _neo4j_driver_instance


async def close_neo4j_driver():
    """Close the Neo4j driver gracefully at shutdown."""
    global _neo4j_driver_instance
    if _neo4j_driver_instance is not None:
        await _neo4j_driver_instance.close()
        _neo4j_driver_instance = None