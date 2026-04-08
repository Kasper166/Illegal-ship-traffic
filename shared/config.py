"""
Configuration management for DARKWATER maritime surveillance system.

Loads environment variables and provides a singleton settings instance.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    demo_mode: bool = False
    database_url: str = ""
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "vessel_tracks"
    api_secret_key: str = "change_me"
    log_level: str = "INFO"
    r2_endpoint_url: str = ""
    r2_bucket_name: str = "darkwater"
    wandb_project: str = "darkwater"

    @property
    def db_configured(self) -> bool:
        """Check if database is configured."""
        return bool(self.database_url)


settings = Settings()
