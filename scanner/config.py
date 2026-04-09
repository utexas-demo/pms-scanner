"""
Configuration loaded from environment variables (with .env support via python-dotenv).
"""

from typing import Optional
from uuid import UUID
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Directory to watch for incoming images
    watch_dir: str = "/data/incoming"

    # Recurse into sub-directories of watch_dir
    watch_recursive: bool = True

    # Seconds to wait after a file appears before uploading (lets writes settle)
    file_settle_seconds: float = 0.5

    # Base URL of the pms-backend, e.g. https://api.example.com
    # The upload path /api/scanned-images/upload is appended automatically.
    backend_base_url: str

    # Bearer token (JWT) issued by the backend
    api_token: str

    # Optional: link every uploaded image to a specific requisition
    requisition_id: Optional[UUID] = None

    # HTTP request timeout in seconds
    upload_timeout_seconds: int = 30

    # Logging level: DEBUG | INFO | WARNING | ERROR
    log_level: str = "INFO"


settings = Settings()
