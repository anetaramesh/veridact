"""FINRA Developer API OAuth2 client.

Authentication flow (client_credentials):
  POST https://ews.fip.finra.org/fip/rest/sts/oauth2/access_token
  → Bearer token used for all subsequent requests.

Environment variables (required unless mocked in tests):
  FINRA_CLIENT_ID      – API credential client ID
  FINRA_CLIENT_SECRET  – API credential client secret

FINRA Developer Center: https://developer.finra.org/docs
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import csv
import io
import httpx

logger = logging.getLogger(__name__)


def _csv_to_dicts(text: str) -> list[dict[str, Any]]:
    """Parse a CSV string (with header row) into a list of dicts."""
    reader = csv.DictReader(io.StringIO(text.strip()))
    return [dict(row) for row in reader]

_TOKEN_URL = "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token"
_BASE_URL = "https://api.finra.org"


class FinraApiError(Exception):
    """Raised when the FINRA API returns an error or credentials are missing."""


class FinraApiClient:
    """Thin async-capable HTTP client for the FINRA Developer API.

    Handles OAuth 2.0 client-credentials token acquisition and transparent
    token refresh (tokens expire after 1 hour).

    Args:
        client_id: FINRA API client ID (defaults to ``FINRA_CLIENT_ID`` env var).
        client_secret: FINRA API client secret (defaults to ``FINRA_CLIENT_SECRET`` env var).
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._client_id = client_id or os.environ.get("FINRA_CLIENT_ID", "")
        self._client_secret = client_secret or os.environ.get("FINRA_CLIENT_SECRET", "")
        self._timeout = timeout
        self._access_token: str | None = None
        self._token_expiry: float = 0.0

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _refresh_token(self) -> None:
        """Fetch a fresh Bearer token using client-credentials grant."""
        if not self._client_id or not self._client_secret:
            raise FinraApiError(
                "FINRA_CLIENT_ID and FINRA_CLIENT_SECRET must be set. "
                "Register at https://developer.finra.org/APICredentials"
            )

        resp = httpx.post(
            _TOKEN_URL,
            params={"grant_type": "client_credentials"},
            auth=(self._client_id, self._client_secret),
            timeout=self._timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._access_token = payload["access_token"]
        # tokens are valid for expires_in seconds; refresh 60 s early
        expires_in = int(payload.get("expires_in", 3600))
        self._token_expiry = time.monotonic() + expires_in - 60
        logger.debug("FINRA token refreshed; valid for ~%ds", expires_in)

    def _ensure_token(self) -> str:
        if self._access_token is None or time.monotonic() >= self._token_expiry:
            self._refresh_token()
        assert self._access_token is not None
        return self._access_token

    # ------------------------------------------------------------------
    # Generic query
    # ------------------------------------------------------------------

    def query(
        self,
        group: str,
        dataset: str,
        compare_filters: list[dict[str, Any]] | None = None,
        fields: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Execute a FINRA Query API request and return the result rows.

        Args:
            group: Dataset group (e.g. ``"Registration"``).
            dataset: Dataset name (e.g. ``"IndividualReport"``).
            compare_filters: List of filter dicts with keys
                ``fieldName``, ``compareType``, ``fieldValue``.
            fields: Fields to include in the response; ``None`` returns all.
            limit: Maximum number of records to return.

        Returns:
            List of record dicts from the FINRA API.

        Raises:
            FinraApiError: On HTTP error or missing credentials.
        """
        token = self._ensure_token()
        params: dict[str, Any] = {"limit": limit}
        if fields:
            params["fields"] = ",".join(fields)
        if compare_filters:
            import json
            params["compareFilters"] = json.dumps(compare_filters)

        url = f"{_BASE_URL}/data/group/{group}/name/{dataset}"
        resp = httpx.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            timeout=self._timeout,
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "json" in content_type:
            return resp.json() or []

        # FINRA public market datasets return CSV; parse into dicts
        return _csv_to_dicts(resp.text)

    # ------------------------------------------------------------------
    # BrokerCheck helpers
    # ------------------------------------------------------------------

    def get_individual_report(self, crd_number: str) -> dict[str, Any] | None:
        """Fetch a BrokerCheck individual report by CRD number.

        Returns the first matching record or ``None`` if not found.
        """
        rows = self.query(
            group="Registration",
            dataset="IndividualReport",
            compare_filters=[
                {"fieldName": "indvlPK", "compareType": "equalTo", "fieldValue": crd_number}
            ],
            fields=["indvlPK", "firstName", "lastName", "currentIaRgstrnCnt", "currentBrokerRgstrnCnt", "disclosuresFlag"],
            limit=1,
        )
        return rows[0] if rows else None

    def get_firm_report(self, crd_number: str) -> dict[str, Any] | None:
        """Fetch a BrokerCheck firm report by CRD number.

        Returns the first matching record or ``None`` if not found.
        """
        rows = self.query(
            group="Registration",
            dataset="FirmReport",
            compare_filters=[
                {"fieldName": "firmPK", "compareType": "equalTo", "fieldValue": crd_number}
            ],
            fields=["firmPK", "firmName", "firmRgstrnSts", "disclosuresFlag"],
            limit=1,
        )
        return rows[0] if rows else None

    def get_disciplinary_actions(self, crd_number: str) -> list[dict[str, Any]]:
        """Return disciplinary action records for a firm or individual CRD."""
        return self.query(
            group="Disciplinary",
            dataset="DisciplinaryActions",
            compare_filters=[
                {"fieldName": "crdNumber", "compareType": "equalTo", "fieldValue": crd_number}
            ],
            limit=50,
        )
