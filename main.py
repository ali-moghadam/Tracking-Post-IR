"""
main.py — Root entry point for deployment platforms that run `python main.py`.
Delegates to the FastAPI app defined in app/main.py via uvicorn.
"""
import uvicorn
from app.core.config import settings


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info",
    )
