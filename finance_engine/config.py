# ============================================================
# finance_engine/config.py — Configurações via .env
# ============================================================

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://atlas:atlas@localhost:5432/atlas_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    ENVIRONMENT: str = "development"
    SECRET_KEY: str = "change-me-in-production"


settings = Settings()
