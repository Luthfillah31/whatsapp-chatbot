import os
from functools import lru_cache
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # OpenRouter AI
    OPENROUTER_API_KEY: str = "test_key"
    OPENROUTER_MODEL: str = "meta-llama/llama-3.3-70b-instruct"
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"

    # Tennis Courts Configuration
    COURT_1_NAME: str = "Tennis Court 1"
    COURT_2_NAME: str = "Tennis Court 2"
    CLUB_OPENING_HOUR: str = "07:00"
    CLUB_CLOSING_HOUR: str = "22:00"
    HOURLY_RATE_USD: int = 40

    # Database
    DATABASE_URL: str = "sqlite:///./tennis_courts.db"

    # Google Calendar (Optional)
    GOOGLE_SERVICE_ACCOUNT_FILE: Optional[str] = ""
    GOOGLE_CALENDAR_ID_COURT_1: Optional[str] = ""
    GOOGLE_CALENDAR_ID_COURT_2: Optional[str] = ""

    # Meta WhatsApp Cloud API
    WHATSAPP_TOKEN: Optional[str] = ""
    WHATSAPP_PHONE_NUMBER_ID: Optional[str] = ""
    WHATSAPP_VERIFY_TOKEN: str = "my_secret_verify_token_123"

    # Evolution API / Baileys Wrapper (Optional)
    EVOLUTION_API_URL: Optional[str] = ""
    EVOLUTION_API_KEY: Optional[str] = ""
    EVOLUTION_INSTANCE_NAME: Optional[str] = "tennis_bot"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
