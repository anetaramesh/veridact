from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path as _Path

from dotenv import load_dotenv
load_dotenv(_Path(__file__).parent.parent.parent / ".env")
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

import src.engine.audit_log as audit_log
from src.api.routes.audit import router as audit_router
from src.api.routes.rules import router as rules_router
from src.api.routes.validate import router as validate_router
from src.api.routes.finra import router as finra_router
from src.finserv.report_gen import router as report_router
from src.engine.governance import GovernanceEngine
from src.rules.loader import load_rules
from src.finra.client import FinraApiClient
from src.finra.provider import FinraDataProvider

logger = logging.getLogger(__name__)

RULES_DIR = Path(__file__).parent.parent.parent / "rules"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """FastAPI lifespan handler — initialise DB and load rule packs on startup."""
    db_path = Path(os.environ.get("AUDIT_DB_PATH", "audit.db"))
    audit_log.DB_PATH = db_path
    await audit_log.init_db(db_path)

    from src.api.routes.rules import _load_active_ids
    all_rules = load_rules(RULES_DIR)
    active_ids = _load_active_ids()
    app.state.rules = [r for r in all_rules if active_ids is None or r.id in active_ids]
    logger.info("Rules: %d total, %d active", len(all_rules), len(app.state.rules))

    # Wire live FINRA/OFAC data provider when credentials are present.
    # Without credentials the governance engine falls back to YAML stub data.
    data_provider = None
    if os.environ.get("FINRA_CLIENT_ID") and os.environ.get("FINRA_CLIENT_SECRET"):
        has_firm = os.environ.get("FINRA_CREDENTIAL_TYPE", "public").lower() == "firm"
        finra_client = FinraApiClient()
        data_provider = FinraDataProvider(finra_client, has_firm_credential=has_firm)
        logger.info(
            "FINRA live data provider enabled (credential_type=%s). "
            "BrokerCheck live lookups: %s.",
            "firm" if has_firm else "public",
            "enabled" if has_firm else "disabled — set FINRA_CREDENTIAL_TYPE=firm to enable",
        )
    else:
        logger.warning(
            "FINRA_CLIENT_ID / FINRA_CLIENT_SECRET not set — "
            "using YAML stub data for sanctions and account checks."
        )

    app.state.governance = GovernanceEngine(rules=app.state.rules, data_provider=data_provider)
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
    app.include_router(report_router)
    app.include_router(rules_router)
    app.include_router(finra_router)

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
