"""Application settings, read from environment variables (or a .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PragMattie Sync CRM API"
    environment: str = "local"
    # SQLAlchemy URL. MySQL in Docker by default; tests override with SQLite.
    database_url: str = "mysql+pymysql://pragmattie_sync:pragmattie_sync@localhost:3306/pragmattie_sync"
    cors_origins: list[str] = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
