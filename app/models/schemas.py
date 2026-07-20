"""
models/schemas.py — Pydantic request / response models.
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, field_validator


# ── Request ──────────────────────────────────────────────────────

class TrackRequest(BaseModel):
    """Body for POST /api/track."""

    trackingCode: str = Field(..., description="20–24 digit Iran Post tracking code")
    phone: str | None = Field(
        default=None,
        description=(
            "Receiver mobile number (optional). "
            "Iran Post now requires this to reveal receiver_name. "
            "Example: '09123456789'"
        ),
    )

    @field_validator("trackingCode")
    @classmethod
    def validate_code(cls, v: str) -> str:
        code = v.strip()
        import re
        if not re.fullmatch(r"\d{20,24}", code):
            raise ValueError("Invalid tracking code — must be 20–24 digits")
        return code

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str | None) -> str | None:
        if v is None:
            return None
        import re
        phone = re.sub(r"[\s\-]", "", v.strip())
        # Accept Iranian mobile: 09xxxxxxxxx or +989xxxxxxxxx or 9xxxxxxxxx
        phone = re.sub(r"^\+98", "0", phone)
        phone = re.sub(r"^98(?=9)", "0", phone)
        if not re.fullmatch(r"09\d{9}", phone):
            raise ValueError("Invalid phone number — expected Iranian mobile, e.g. 09123456789")
        return phone


# ── Sub-models ───────────────────────────────────────────────────

class TrackingEvent(BaseModel):
    """A single timeline event in the tracking history."""

    date: str = ""
    location: str = ""
    status: str = ""


# ── Response ─────────────────────────────────────────────────────

class TrackResponse(BaseModel):
    """Response body for POST /api/track (success or failure)."""

    success: bool
    tracking_code: str
    status: str = ""
    receiver_name: str = ""
    origin: str = ""
    destination: str = ""
    last_update: str = ""
    is_delivered: bool = False
    events: List[TrackingEvent] = Field(default_factory=list)
    raw_html_parsed: bool = True
    error: str | None = None


class HealthResponse(BaseModel):
    """Response body for GET /health."""

    status: str
    ts: str
    mode: str

