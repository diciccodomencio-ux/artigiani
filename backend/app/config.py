from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    database_url: str
    uploads_dir: Path = BASE_DIR / "uploads"
    cors_origins: str = "http://localhost:5173"

    secret_key: str = "dev_secret_change_me"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # Twilio legacy - kept temporarily for compatibility
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_whatsapp_from: str | None = None

    # Meta WhatsApp Cloud API
    meta_whatsapp_token: str | None = Field(
        default=None,
        validation_alias="META_WHATSAPP_TOKEN",
    )

    meta_phone_number_id: str | None = Field(
        default=None,
        validation_alias="META_PHONE_NUMBER_ID",
    )

    meta_waba_id: str | None = Field(
        default=None,
        validation_alias="META_WABA_ID",
    )

    whatsapp_verify_token: str | None = Field(
        default=None,
        validation_alias="WHATSAPP_VERIFY_TOKEN",
    )

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )


settings = Settings()