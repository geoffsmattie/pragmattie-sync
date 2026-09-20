"""Orchestrator settings, read from environment variables (or a .env file)."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "PragMattie Sync Orchestrator"
    # Same MySQL database as the CRM; orchestrator tables are prefixed "sdlc_".
    database_url: str = (
        "mysql+pymysql://pragmattie_sync:pragmattie_sync@localhost:3306/pragmattie_sync"
    )
    cors_origins: list[str] = ["http://localhost:5173"]

    # GitHub access for the signals collector and backlog script.
    # A fine-grained token scoped to this one repository.
    github_token: str = ""
    github_repo: str = ""  # "owner/name", e.g. "geoffsmattie/pragmattie-sync"
    github_api_url: str = "https://api.github.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
