"""Orchestrator settings, read from environment variables (or a .env file)."""

from functools import lru_cache
from typing import Literal

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

    # The PR risk agent (Phase 4). Model ids live here, never in code, so any run can be
    # reproduced from its audit row and a model change is a config change.
    anthropic_api_key: str = ""
    risk_model: str = "claude-sonnet-5"
    # off: the agents do nothing and write nothing to GitHub. shadow: they comment, label and
    # record decisions, but the risk-gate status always passes. enforce: the status gates merges.
    orchestrator_mode: Literal["off", "shadow", "enforce"] = "off"
    poll_seconds: int = 30
    agent_timeout_seconds: float = 60.0
    risk_max_output_tokens: int = 4000
    diff_char_limit: int = 60000  # about 15k tokens of diff, risky files first


@lru_cache
def get_settings() -> Settings:
    return Settings()
