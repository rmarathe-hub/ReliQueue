from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_async_database_url(url: str) -> str:
    """Accept Railway/Heroku-style postgres:// URLs for async SQLAlchemy."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://") and "+asyncpg" not in url and "+psycopg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ReliQueue"
    app_env: str = "development"
    debug: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "postgresql+asyncpg://reliqueue:reliqueue@localhost:5432/reliqueue"
    test_database_url: str = "postgresql+asyncpg://reliqueue:reliqueue@localhost:5432/reliqueue_test"
    worker_lease_seconds: int = 60
    worker_recovery_interval_seconds: int = 30
    retry_base_delay_seconds: float = 1.0
    retry_max_delay_seconds: float = 300.0
    retry_jitter_enabled: bool = True

    @field_validator("database_url", "test_database_url")
    @classmethod
    def normalize_database_urls(cls, value: str) -> str:
        return normalize_async_database_url(value)


settings = Settings()
