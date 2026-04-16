"""FastAPI app factory with CORS, routers, and SPA static file serving."""

import os
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

# Module-level singletons shared by route modules
scan_lock = threading.Lock()
scan_state: dict = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "error": None,
}

_SPA_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "dist")


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    app = FastAPI(title="Coin Scanner API")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    from api.routes.scanner import router as scanner_router
    from api.routes.sentiment import router as sentiment_router
    from api.routes.portfolio import router as portfolio_router

    app.include_router(scanner_router, prefix="/api")
    app.include_router(sentiment_router, prefix="/api")
    app.include_router(portfolio_router, prefix="/api")

    # SPA static file serving at /app/
    if os.path.isdir(_SPA_DIR):
        app.mount(
            "/app/assets",
            StaticFiles(directory=os.path.join(_SPA_DIR, "assets")),
            name="spa-assets",
        )

        @app.get("/app/{path:path}", response_model=None)
        def spa_catch_all(path: str = ""):
            full = os.path.join(_SPA_DIR, path)
            if path and os.path.isfile(full):
                return FileResponse(full)
            index = os.path.join(_SPA_DIR, "index.html")
            if os.path.isfile(index):
                return FileResponse(index)
            return HTMLResponse(
                "React SPA not built. Run: cd web && npm run build",
                status_code=404,
            )

        @app.get("/app/", response_model=None)
        def spa_index():
            index = os.path.join(_SPA_DIR, "index.html")
            if os.path.isfile(index):
                return FileResponse(index)
            return HTMLResponse(
                "React SPA not built. Run: cd web && npm run build",
                status_code=404,
            )

    return app
