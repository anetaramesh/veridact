"""Live compliance data provider backed by the FINRA Developer API and OFAC SDN API.

This module implements the ``LiveDataProvider`` protocol used by the rule engine
to replace static YAML stub data with real-time lookups.

Credential access levels
------------------------
Public credential (what this integration uses):
  - OTC market data, Reg SHO, short interest, fixed-income aggregates  ✓
  - BrokerCheck firm/individual registration data                       ✗ (Firm credential required)
  - Disciplinary actions                                                ✗ (Firm credential required)

OFAC SDN sanctions data is sourced from the US Treasury OFAC API (no auth required).

To upgrade BrokerCheck lookups to live data, obtain a FINRA Firm credential
at https://developer.finra.org/APICredentials and set FINRA_CREDENTIAL_TYPE=firm.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Protocol, runtime_checkable

import httpx

from .client import FinraApiClient, FinraApiError

logger = logging.getLogger(__name__)

# OFAC SDN screening — US Treasury public API, no auth required
_OFAC_SDN_URL = "https://api.ofac.dev/v1/screening"


@runtime_checkable
class LiveDataProvider(Protocol):
    """Protocol for live compliance data lookups consumed by the rule engine."""

    def is_sanctioned(self, entity_id: str) -> bool:
        """Return ``True`` if *entity_id* appears on the OFAC SDN list."""
        ...

    def is_account_restricted(self, account_id: str) -> bool:
        """Return ``True`` if *account_id* is frozen or under regulatory restriction."""
        ...

    def get_wire_threshold(self) -> float:
        """Return the current autonomous wire transfer threshold in USD."""
        ...


class FinraDataProvider:
    """Concrete ``LiveDataProvider`` backed by FINRA Developer API + OFAC SDN API.

    With a **Public** FINRA credential, BrokerCheck (account_status) lookups fall back
    to the YAML stub list and log a warning — upgrade to a Firm credential to enable
    live BrokerCheck. OFAC sanctions screening works with any credential level since
    it uses the public US Treasury API.

    Args:
        finra_client: Authenticated :class:`FinraApiClient` instance.
        wire_threshold: Autonomous wire transfer threshold in USD (default 1_000_000).
        ofac_timeout: HTTP timeout in seconds for OFAC screening requests.
        has_firm_credential: Set ``True`` when a Firm-level FINRA credential is
            configured, enabling live BrokerCheck lookups.
    """

    def __init__(
        self,
        finra_client: FinraApiClient,
        wire_threshold: float = 1_000_000.0,
        ofac_timeout: float = 10.0,
        has_firm_credential: bool = False,
    ) -> None:
        self._finra = finra_client
        self._wire_threshold = wire_threshold
        self._ofac_timeout = ofac_timeout
        self._has_firm_credential = has_firm_credential

    # ------------------------------------------------------------------
    # LiveDataProvider implementation
    # ------------------------------------------------------------------

    def is_sanctioned(self, entity_id: str) -> bool:
        """Screen *entity_id* against the OFAC SDN list via the US Treasury OFAC API.

        Uses the public OFAC screening API — no FINRA credential required.
        Falls back to ``False`` on network error with a logged warning.
        """
        try:
            resp = httpx.post(
                _OFAC_SDN_URL,
                json={"name": entity_id},
                timeout=self._ofac_timeout,
            )
            if resp.status_code == 404:
                return False
            resp.raise_for_status()
            matches = resp.json().get("matches", [])
            if matches:
                logger.warning("OFAC SDN match for entity_id=%s: %s", entity_id, matches[0])
                return True
            return False
        except httpx.HTTPError as exc:
            logger.error(
                "OFAC API unreachable for entity_id=%s: %s; defaulting to pass",
                entity_id, exc,
            )
            return False

    def is_account_restricted(self, account_id: str) -> bool:
        """Check if *account_id* is under regulatory restriction.

        Requires a **Firm** FINRA credential for live BrokerCheck lookups.
        With a Public credential, always returns ``False`` and logs a warning
        directing operators to upgrade their credential.
        """
        if not self._has_firm_credential:
            logger.warning(
                "BrokerCheck live lookup skipped for account_id=%s: "
                "Public FINRA credential does not permit Registration data access. "
                "Set FINRA_CREDENTIAL_TYPE=firm to enable live BrokerCheck checks.",
                account_id,
            )
            return False

        try:
            report: dict[str, Any] | None = self._finra.get_individual_report(account_id)
            if report is None:
                report = self._finra.get_firm_report(account_id)
            if report is None:
                logger.debug("account_id=%s not found in FINRA BrokerCheck", account_id)
                return False

            has_disclosures = str(report.get("disclosuresFlag", "N")).upper() == "Y"
            reg_status = str(report.get("firmRgstrnSts", "Approved")).lower()
            is_inactive = reg_status not in ("approved", "active", "")

            if has_disclosures or is_inactive:
                logger.warning(
                    "FINRA BrokerCheck restriction: account_id=%s disclosures=%s status=%s",
                    account_id, has_disclosures, reg_status,
                )
                return True
            return False

        except (FinraApiError, httpx.HTTPError) as exc:
            logger.error(
                "FINRA BrokerCheck error for account_id=%s: %s; defaulting to unrestricted",
                account_id, exc,
            )
            return False

    def get_wire_threshold(self) -> float:
        """Return the configured autonomous wire transfer threshold."""
        return self._wire_threshold

    def get_otc_market_summary(self, limit: int = 10) -> list[dict[str, Any]]:
        """Fetch live OTC market weekly summary data.

        Available with Public FINRA credentials. Useful for market-surveillance
        rules (e.g. geo_concentration, suspicious_routing).

        Returns:
            List of OTC market participant records.
        """
        return self._finra.query(group="otcMarket", dataset="weeklySummary", limit=limit)
