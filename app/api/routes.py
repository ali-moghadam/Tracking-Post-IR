"""
api/routes.py — FastAPI router: /health, /api/track, /api/debug.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.logging import get_logger
from app.models.schemas import HealthResponse, TrackRequest, TrackResponse
from app.services.scraper_service import scrape_tracking, scrape_raw_html

logger = get_logger(__name__)
router = APIRouter()


# ── Root ──────────────────────────────────────────────────────────

@router.get("/", tags=["meta"])
async def root() -> JSONResponse:
    """Root endpoint — returns API info."""
    return JSONResponse(content={
        "name": "Iran Post Tracking API",
        "version": "2.0.0",
        "status": "running",
        "endpoints": {
            "health":    "GET  /health",
            "track":     "POST /api/track   body: {\"trackingCode\": \"...\"}",
            "debug":     "POST /api/debug   body: {\"trackingCode\": \"...\"}",
            "docs":      "GET  /docs",
        },
    })


# ── Health ────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    """Liveness probe — always returns 200 OK."""
    return HealthResponse(
        status="ok",
        ts=datetime.now(timezone.utc).isoformat(),
        mode="web-scraper",
    )


# ── Track ─────────────────────────────────────────────────────────

@router.post("/api/track", response_model=TrackResponse, tags=["tracking"])
async def track(body: TrackRequest) -> TrackResponse:
    """
    Submit a tracking code to Iran Post and return structured results.

    - **trackingCode**: 20–24 digit numeric string.
    """
    logger.info("[track] request code=%s", body.trackingCode)
    try:
        result = await scrape_tracking(body.trackingCode)
        return result
    except Exception as exc:
        logger.exception("[track] unexpected error code=%s: %s", body.trackingCode, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


# ── Debug — returns raw POST response HTML ────────────────────────

@router.post("/api/debug", response_class=HTMLResponse, tags=["debug"])
async def debug_html(body: TrackRequest) -> HTMLResponse:
    """
    Returns the raw HTML that the scraper receives from tracking.post.ir
    after submitting the form.  Use this to inspect selectors when parsed
    results are empty or incorrect.
    """
    logger.info("[debug] request code=%s", body.trackingCode)
    try:
        html = await scrape_raw_html(body.trackingCode)
        if html is None:
            raise HTTPException(status_code=502, detail="Scrape returned no HTML")
        return HTMLResponse(content=html)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("[debug] error code=%s: %s", body.trackingCode, exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

