"""Settings from env vars / ConfigMaps. No hard-coded localhost (rule 12)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    env: str = "dev"
    log_level: str = "INFO"
    internal_token: str = ""
    jwt_secret: str = ""

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "ideas"
    postgres_user: str = "ideas"
    postgres_password: str = ""
    database_url: str = ""  # overrides the postgres_* parts when set (tests use sqlite)
    redis_url: str = "redis://redis:6379/0"
    qdrant_url: str = "http://qdrant:6333"

    profile_url: str = "http://profile:8000"
    orchestrator_url: str = "http://orchestrator:8000"
    tools_url: str = "http://tools:8000"
    kb_url: str = "http://kb:8000"
    analyst_url: str = "http://analyst:8000"
    ideation_url: str = "http://ideation:8000"
    validators_url: str = "http://validators:8000"
    scorer_url: str = "http://scorer:8000"
    verdict_url: str = "http://verdict:8000"
    critic_url: str = "http://critic:8000"
    agentops_url: str = "http://agentops:8000"

    ui_origin: str = ""
    llm_mode: str = "live"
    llm_base_url: str = ""
    llm_api_key: str = ""
    hosted_model: str = ""
    llm_fixtures_dir: str = "tests/fixtures/llm"

    config_dir: str = "/config"
    bad_release: bool = False

    @property
    def sqlalchemy_url(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
