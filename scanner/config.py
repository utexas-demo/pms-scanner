"""
Configuration loaded from environment variables (with .env support via python-dotenv).
"""

from pathlib import Path
from uuid import UUID

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Directory to watch for incoming PDFs
    watch_dir: str = "/data/incoming"

    # Seconds to wait after a file appears before claiming it (lets writes settle)
    file_settle_seconds: float = 10.0

    # How often the batch runner fires (seconds)
    cron_interval_seconds: int = 60

    # Port for the live progress dashboard
    dashboard_port: int = 8080

    # Base URL of the pms-backend, e.g. https://api.example.com
    backend_base_url: str

    # Bearer token (JWT) issued by the backend
    api_token: str

    # Optional: link every uploaded page to a specific requisition
    requisition_id: UUID | None = None

    # HTTP request timeout in seconds
    upload_timeout_seconds: int = 30

    # Maximum upload retry attempts before giving up on a page
    upload_max_retries: int = 3

    # Maximum wait between retries (seconds, for exponential back-off ceiling)
    upload_retry_max_wait_seconds: int = 10

    # Logging level: DEBUG | INFO | WARNING | ERROR
    log_level: str = "INFO"

    @property
    def inprogress_dir(self) -> Path:
        return Path(self.watch_dir) / "in-progress"

    @property
    def processed_dir(self) -> Path:
        return Path(self.watch_dir) / "processed"


settings = Settings()  # type: ignore[call-arg]
