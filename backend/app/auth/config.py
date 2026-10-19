from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "local"
    auth_mode: str = "dev"
    auth_issuer: str = "http://localhost:8000/dev-auth"
    auth_audience: str = "goldpatharchery-api"
    dev_jwt_secret: str = "change-me-local-only"
    dev_token_ttl_minutes: int = 60

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
