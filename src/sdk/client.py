from __future__ import annotations

import logging
from typing import Any

import httpx

from .models import ValidationResult

logger = logging.getLogger(__name__)


class AuditorClient:
    """Synchronous and asynchronous client for the Veridact validation API.

    Usage (sync)::

        client = AuditorClient(base_url="http://localhost:8000", api_key="secret")
        result = client.validate(
            action_type="wire_transfer",
            parameters={"amount": 5000, "recipient_id": "ACME-CORP"},
            context={},
            agent_id="my-agent-001",
        )
        if not result.approved:
            raise RuntimeError(f"Blocked: {result.rationale}")

    Usage (async)::

        result = await client.validate_async(...)

    Args:
        base_url: Base URL of the Veridact API (e.g. ``"http://localhost:8000"``).
        api_key: Optional API key sent as the ``X-API-Key`` header.
    """

    def __init__(self, base_url: str, api_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._headers: dict[str, str] = {"X-API-Key": api_key} if api_key else {}

    def _build_payload(
        self,
        action_type: str,
        parameters: dict[str, Any],
        context: dict[str, Any],
        agent_id: str,
    ) -> dict[str, Any]:
        """Assemble the JSON body for a ``POST /validate`` request.

        Args:
            action_type: Category of action the agent is attempting.
            parameters: Action-specific payload fields.
            context: Ambient metadata available to rule evaluators.
            agent_id: Identifier of the calling agent.

        Returns:
            Dict ready for JSON serialisation.
        """
        return {
            "action_type": action_type,
            "parameters": parameters,
            "context": context,
            "agent_id": agent_id,
        }

    def validate(
        self,
        action_type: str,
        parameters: dict[str, Any],
        context: dict[str, Any],
        agent_id: str,
    ) -> ValidationResult:
        """Synchronously validate an agent action against all compliance rules.

        Args:
            action_type: Category of action (e.g. ``"wire_transfer"``).
            parameters: Action-specific fields evaluated by rules.
            context: Ambient context (account metadata, session info).
            agent_id: Identifier of the requesting agent.

        Returns:
            :class:`~src.sdk.models.ValidationResult` with approval decision and any violations.

        Raises:
            httpx.HTTPStatusError: If the server returns a non-2xx response.
            httpx.TimeoutException: If the request exceeds the 10-second timeout.
        """
        payload = self._build_payload(action_type, parameters, context, agent_id)
        logger.debug("validate(sync) agent=%s action=%s", agent_id, action_type)
        with httpx.Client(headers=self._headers) as client:
            resp = client.post(f"{self._base_url}/validate", json=payload, timeout=10.0)
            resp.raise_for_status()
        return ValidationResult.model_validate(resp.json())

    async def validate_async(
        self,
        action_type: str,
        parameters: dict[str, Any],
        context: dict[str, Any],
        agent_id: str,
    ) -> ValidationResult:
        """Asynchronously validate an agent action against all compliance rules.

        Args:
            action_type: Category of action (e.g. ``"wire_transfer"``).
            parameters: Action-specific fields evaluated by rules.
            context: Ambient context (account metadata, session info).
            agent_id: Identifier of the requesting agent.

        Returns:
            :class:`~src.sdk.models.ValidationResult` with approval decision and any violations.

        Raises:
            httpx.HTTPStatusError: If the server returns a non-2xx response.
            httpx.TimeoutException: If the request exceeds the 10-second timeout.
        """
        payload = self._build_payload(action_type, parameters, context, agent_id)
        logger.debug("validate(async) agent=%s action=%s", agent_id, action_type)
        async with httpx.AsyncClient(headers=self._headers) as client:
            resp = await client.post(f"{self._base_url}/validate", json=payload, timeout=10.0)
            resp.raise_for_status()
        return ValidationResult.model_validate(resp.json())
