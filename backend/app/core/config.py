from pydantic_settings import BaseSettings, SettingsConfigDict


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
    retry_base_delay_seconds: float = 1.0
    retry_max_delay_seconds: float = 300.0
    retry_jitter_enabled: bool = True


settings = Settings()
