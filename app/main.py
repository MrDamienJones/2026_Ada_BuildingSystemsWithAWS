"""FastAPI application factory.

Creates and configures the Live Poll App with CORS middleware and all
routers registered. Entry point for uvicorn: ``app.main:app``.
"""

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.routers.health import router as health_router
from app.routers.polls import router as polls_router
from app.routers.presenter import router as presenter_router
from app.routers.websocket import router as ws_router


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance.

    - Registers CORS middleware allowing all origins (demo app).
    - Includes all routers: polls, presenter, health, and websocket.
    """
    application = FastAPI(
        title="Live Poll App",
        description="Real-time polling for ADA Sheffield",
    )

    # CORS: allow_credentials=True requires explicit origins (not "*").
    # In production, FrontendStack injects the CloudFront domain via ALLOWED_ORIGINS env var.
    # Locally, defaults to localhost:8000.
    allowed_origins = os.environ.get("ALLOWED_ORIGINS", "http://localhost:8000").split(",")

    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )

    application.include_router(polls_router)
    application.include_router(presenter_router)
    application.include_router(health_router)
    application.include_router(ws_router)

    # Serve frontend static files if the directory exists (ECS/EC2 deployments)
    # Mounted at /static to avoid shadowing API routes
    frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
    if frontend_dir.is_dir():
        application.mount("/static", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

    return application


app = create_app()
