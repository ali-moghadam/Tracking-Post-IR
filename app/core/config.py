"""
core/config.py — Application configuration via environment variables.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    # Server
    port: int = 3001
    host: str = "0.0.0.0"
    debug: bool = False

    # Scraper
    tracking_url: str = "https://tracking.post.ir/"
    timeout_seconds: float = 20.0
    max_retries: int = 2
    retry_sleep_seconds: float = 1.5

    # TLS impersonation — passed to curl_cffi as the `impersonate` target.
    # Valid values: "chrome124", "chrome120", "chrome110", "safari17_0", etc.
    # See: https://curl-cffi.readthedocs.io/en/latest/impersonate.html
    impersonate: str = "chrome124"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

