from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://heroiq:heroiq_password@localhost:5432/heroiq"

    # Pinecone
    PINECONE_API_KEY: str = ""
    PINECONE_INDEX_NAME: str = "heroiq-search"

    # OpenAI
    OPENAI_API_KEY: str = ""

    # App
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False

    # Chunking
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    MIN_CHUNK_SIZE: int = 50

    # Search
    SEARCH_TOP_K: int = 5
    SEARCH_RESULTS_LIMIT: int = 3

    # Sentry
    SENTRY_DSN: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
