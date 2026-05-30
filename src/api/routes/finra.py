from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/finra", tags=["finra"])


@router.get("/status", summary="FINRA API integration status")
async def finra_status(request: Request) -> JSONResponse:
    """Return current FINRA API connection status and data source availability."""
    from src.finra.provider import FinraDataProvider

    has_creds = bool(
        os.environ.get("FINRA_CLIENT_ID") and os.environ.get("FINRA_CLIENT_SECRET")
    )
    credential_type = os.environ.get("FINRA_CREDENTIAL_TYPE", "public").lower()

    data_provider = getattr(request.app.state, "governance", None)
    provider_active = (
        data_provider is not None
        and hasattr(data_provider, "_data_provider")
        and isinstance(getattr(data_provider, "_data_provider", None), FinraDataProvider)
    )

    return JSONResponse({
        "connected": has_creds and provider_active,
        "credential_type": credential_type if has_creds else None,
        "data_sources": {
            "ofac_sanctions": {
                "status": "live" if has_creds else "stub",
                "description": "OFAC SDN list via US Treasury public API",
                "requires": "any credential",
            },
            "brokercheck": {
                "status": "live" if (has_creds and credential_type == "firm") else (
                    "unavailable" if has_creds else "stub"
                ),
                "description": "FINRA BrokerCheck firm/individual registration",
                "requires": "firm credential",
            },
            "otc_market_data": {
                "status": "live" if has_creds else "unavailable",
                "description": "OTC market weekly summary, Reg SHO data",
                "requires": "public credential",
            },
        },
    })


@router.get("/data/otc-summary", summary="Live OTC market weekly summary")
async def otc_summary(request: Request, limit: int = 10) -> JSONResponse:
    """Fetch live OTC market data from FINRA (requires active connection)."""
    from src.finra.provider import FinraDataProvider

    governance = getattr(request.app.state, "governance", None)
    if governance is None:
        return JSONResponse({"error": "Governance engine not initialised"}, status_code=503)

    provider = getattr(governance, "_data_provider", None)
    if not isinstance(provider, FinraDataProvider):
        return JSONResponse(
            {"error": "FINRA live data provider not configured. Set FINRA_CLIENT_ID and FINRA_CLIENT_SECRET."},
            status_code=503,
        )

    try:
        rows = provider.get_otc_market_summary(limit=min(limit, 50))
        return JSONResponse({"count": len(rows), "data": rows})
    except Exception as exc:
        logger.error("OTC summary fetch failed: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=502)
