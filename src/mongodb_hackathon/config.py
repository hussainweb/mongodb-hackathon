"""Application settings loaded from environment variables and `.env`."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for FinishLine (Track 3: Finish the Job)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mongodb_uri: str = Field(default="", alias="MONGODB_URI")
    mongodb_db: str = Field(default="finishline", alias="MONGODB_DB")

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")
    embedding_model: str = Field(
        default="text-embedding-3-small", alias="EMBEDDING_MODEL"
    )
    embedding_dimensions: int = Field(default=1536, alias="EMBEDDING_DIMENSIONS")

    langsmith_tracing: bool = Field(default=True, alias="LANGSMITH_TRACING")
    langsmith_api_key: str = Field(default="", alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(
        default="mongodb-hackathon", alias="LANGSMITH_PROJECT"
    )

    elevenlabs_api_key: str = Field(default="", alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = Field(
        default="JBFqnCBsd6RMkjVDRZzb", alias="ELEVENLABS_VOICE_ID"
    )

    github_sandbox_repo: str = Field(default="", alias="GITHUB_SANDBOX_REPO")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")

    target_service_url: str = Field(
        default="http://127.0.0.1:8001", alias="TARGET_SERVICE_URL"
    )
    server_host: str = Field(default="0.0.0.0", alias="SERVER_HOST")
    control_room_port: int = Field(default=8000, alias="CONTROL_ROOM_PORT")
    target_service_port: int = Field(default=8001, alias="TARGET_SERVICE_PORT")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings instance."""
    return Settings()
