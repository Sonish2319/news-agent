
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file (…/daily-news-agent/.env)
# so the API works regardless of which directory uvicorn is launched from.
# config.py lives at: daily-news-agent/src/news_agent/config.py
#   parents[0] = daily-news-agent/src/news_agent/
#   parents[1] = daily-news-agent/src/
#   parents[2] = daily-news-agent/   <-- .env is here
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

# lru_cache => Caches the settings object so it doesn't need to be recreated repeatedly.

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    ollama_model: str = "qwen3:4b"
    ollama_url: str = "http://localhost:11434"
    ollama_timeout: int = Field(default=800, ge=1, le=900)

    gmail_address: str
    gmail_app_password: SecretStr
    email_to: str

    top_stories: int = Field(default=20, ge=1, le=30)
    rss_entries_per_feed: int = Field(default=20, ge=1, le=100)

    database_path: Path = Path("data/news.db")
    log_level: str = "INFO"
    timezone_name: str = "Asia/Kathmandu"

    @field_validator("ollama_url")
    @classmethod
    def normalize_ollama_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        value = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if value not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {allowed}")
        return value


# @property lets you access a method like an attribute. ex: settings.timezone
    @property
    def timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone_name)

    @property
    def ollama_chat_url(self) -> str:
        return f"{self.ollama_url}/api/chat"

#lru_cache stores the result of a function call so that subsequent calls with the same arguments can reuse the cached result.

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
