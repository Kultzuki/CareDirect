from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

# Docker publishes only 127.0.0.1:5432, and `localhost` may resolve to ::1 first and stall.
_DEV_DB = "postgresql+psycopg://caredirect:caredirect_dev_only@127.0.0.1:5432/caredirect"


class Settings(BaseSettings):
    # Reads the repo-root .env if present. Unrelated keys (e.g. PAYPAL_*) are ignored:
    # this slice makes no PayPal calls and does not load PayPal credentials.
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    app_env: str = "development"
    database_url: str = _DEV_DB
    test_database_url: str = _DEV_DB.rsplit("/", 1)[0] + "/caredirect_test"
    cors_origins: str = "http://localhost:3000"

    # Private document storage. Relative paths resolve against the repo root.
    storage_dir: str = "storage"
    storage_backend: str = "local"
    max_upload_mb: int = 20
    max_upload_pages: int = 20
    upload_token_ttl_minutes: int = 60
    upload_token_max_ttl_minutes: int = 1440

    # Auto uses Gemini when a key is set, otherwise recorded synthetic replay.
    document_ai_provider: str = "auto"
    document_ai_model: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    gemini_rpm: int = 5
    gemini_tpm: int = 250000
    gemini_rpd: int = 20
    gemini_quota_file: str = "storage/gemini-quota.sqlite3"

    # DeepSeek API for Care Episode Intelligence
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.goedelmachines.com/v1"
    deepseek_model: str = "deepseek/deepseek-v4.1-flash"
    deepseek_thinking: bool = False
    deepseek_max_tokens: int = 3000

    paypal_environment: str = "sandbox"
    paypal_base_url: str = "https://api-m.sandbox.paypal.com"
    paypal_client_id: str = ""
    paypal_client_secret: str = ""
    paypal_expected_merchant_id: str = ""
    paypal_binding_capture_id: str = ""
    paypal_provider_email: str = ""
    paypal_buyer_email: str = ""
    paypal_enabled: bool = False
    paypal_webhook_id: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_dir)
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
