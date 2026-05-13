"""
app/main.py — FastAPI application factory and entry point.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.api.routes import router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging

setup_logging(debug=settings.debug)
logger = get_logger(__name__)

# ── Application factory ──────────────────────────────────────────

def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    app = FastAPI(
        title="Iran Post Tracking API",
        description="Scraping proxy for https://tracking.post.ir/",
        version="1.0.0",
    )

    # CORS — mirrors cors({ origin: '*' }) in Node.js
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Global validation-error handler → 400 (mirrors Express behaviour)
    @app.exception_handler(ValidationError)
    async def validation_exception_handler(request: Request, exc: ValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": exc.errors()},
        )

    app.include_router(router)

    @app.on_event("startup")
    async def on_startup() -> None:
        logger.info("📦  Iran Post Web Scraper  v2.0")
        logger.info("    Listening → http://%s:%d", settings.host, settings.port)
        logger.info("    Target    → %s", settings.tracking_url)
        logger.info("    Mode      → real browser simulation + BeautifulSoup HTML parsing")

    return app


app = create_app()

# ── Dev entry point (python app/main.py) ──────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )

