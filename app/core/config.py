from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Database Configuration
    DATABASE_URL: str

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

    MEM0_API_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
        validate_default=True
    )


settings = Settings()