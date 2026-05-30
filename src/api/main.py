from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import src.engine.audit_log as audit_log
from src.api.routes.audit import router as audit_router
from src.api.routes.validate import router as validate_router
from src.engine.governance import GovernanceEngine
from src.rules.loader import load_rules

logger = logging.getLogger(__name__)

RULES_DIR = Path(__file__).parent.parent.parent / "rules"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan handler — initialise DB and load rule packs on startup."""
    db_path = Path(os.environ.get("AUDIT_DB_PATH", "audit.db"))
    audit_log.DB_PATH = db_path
    await audit_log.init_db(db_path)

    app.state.rules = load_rules(RULES_DIR)
    app.state.governance = GovernanceEngine(rules=app.state.rules)
    app.state.policy_set = ",".join(
        sorted(p.name for p in RULES_DIR.glob("*.yaml"))
    )
    logger.info("Veridact startup complete: %d rules loaded", len(app.state.rules))
    yield
    logger.info("Veridact shutdown.")


def create_app() -> FastAPI:
    """Construct and return the Veridact FastAPI application.

    Returns:
        Configured :class:`fastapi.FastAPI` instance with all routers attached.
    """
    app = FastAPI(
        title="Veridact",
        version="0.1.0",
        description="Real-time compliance middleware for autonomous AI agents.",
        lifespan=lifespan,
    )
    app.include_router(validate_router)
    app.include_router(audit_router)

    @app.get("/health", summary="Liveness probe")
    async def health() -> JSONResponse:
        """Return service status and number of loaded rules."""
        return JSONResponse({"status": "ok", "rules_loaded": len(app.state.rules)})

    # Serve React dashboard build if it exists
    dashboard_dist = Path(__file__).parent.parent.parent / "dashboard" / "dist"
    if dashboard_dist.exists():
        app.mount("/dashboard", StaticFiles(directory=str(dashboard_dist), html=True), name="dashboard")

    return app


app = create_app()
