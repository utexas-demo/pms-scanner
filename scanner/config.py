"""
Configuration loaded from environment variables (with .env support via python-dotenv).
"""

from pathlib import Path
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

    # PMS backend upload endpoint, e.g. https://api.example.com/v1/images/upload
    backend_upload_url: str

    # Bearer token for the backend API
    api_token: str

    # HTTP request timeout in seconds
    upload_timeout_seconds: int = 30

    # Logging level: DEBUG | INFO | WARNING | ERROR
    log_level: str = "INFO"


settings = Settings()
