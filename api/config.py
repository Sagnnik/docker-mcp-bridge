from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="allow"
    )
    mcp_url: str = "http://localhost:8811/mcp"
    redis_enabled: bool = False
    redis_url: Optional[str] = "redis://localhost:6379"

    # API keys
    openai_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None

    # Langfuse settings
    langfuse_enabled: bool = False
    langfuse_base_url: Optional[str] = "http://localhost:3000"
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None

    # Infisical settings
    infisical_enabled: bool = False
    infisical_url: Optional[str] = "http://localhost:8080"
    infisical_token: Optional[str] = None
    infisical_env: Optional[str] = 'dev'
    infisical_proj: Optional[str] = 'docker-mcp'

settings = Settings()