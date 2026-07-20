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
    # The image CAPTCHA solves ~60% of the time per attempt, so the budget
    # needs to be generous — 6 attempts puts overall success above 99%.
    max_retries: int = 5
    retry_sleep_seconds: float = 1.5

    # TLS impersonation — passed to curl_cffi as the `impersonate` target.
    # Valid values: "chrome124", "chrome120", "chrome110", "safari17_0", etc.
    # See: https://curl-cffi.readthedocs.io/en/latest/impersonate.html
    impersonate: str = "chrome124"

    # CAPTCHA solving (CapSolver — https://capsolver.com)
    # Used for reCAPTCHA/hCaptcha if present.
    capsolver_api_key: str = ""

    # Image CAPTCHA solving — TrueCaptcha (https://truecaptcha.org)
    # Free tier: 100 solves/day. Sign up and get userid + apikey.
    truecaptcha_userid: str = ""
    truecaptcha_apikey: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

