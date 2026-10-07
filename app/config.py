"""Application configuration.

All settings can be overridden with environment variables prefixed with ``CERTGEN_``
(e.g. ``CERTGEN_DATABASE_URL``) or via a ``.env`` file in the working directory.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CERTGEN_", extra="ignore")

    app_name: str = "Bulk Certificate Generator"
    log_level: str = "INFO"

    # Any SQLAlchemy URL works; SQLite is the zero-setup default.
    # PostgreSQL example: postgresql+psycopg://user:pass@localhost:5432/certgen
    database_url: str = f"sqlite:///{(DATA_DIR / 'certgen.db').as_posix()}"

    # Where generated PDF files are written.
    storage_dir: Path = DATA_DIR / "certificates"

    # "thread": jobs are processed by background worker threads (default).
    # "inline": jobs are processed synchronously inside the request (used by tests).
    worker_mode: Literal["thread", "inline"] = "thread"
    worker_count: int = Field(default=2, ge=1, le=32)

    max_recipients_per_job: int = Field(default=5000, ge=1)
    max_csv_bytes: int = Field(default=5 * 1024 * 1024, ge=1024)

    # How many times a certificate is attempted when an unexpected (possibly
    # transient) error occurs. Deterministic template errors are never retried.
    cert_max_attempts: int = Field(default=2, ge=1, le=10)

    # Used to build the verification URL embedded in each certificate's QR code.
    public_base_url: str = "http://localhost:8000"


@lru_cache
def get_settings() -> Settings:
    return Settings()
