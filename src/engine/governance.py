"""Microsoft Agent Governance Toolkit integration layer.

This module wraps the ``agent-os`` PyPI package (Microsoft Agent Governance
Toolkit) and exposes a single ``GovernanceEngine`` that sits in front of the
Veridact YAML rule evaluator.

The governance engine adds a second enforcement layer on top of the rule packs:
  1. YAML rule packs (``rule_engine.evaluate_rules``) — fast, local, deterministic.
  2. Agent Governance Toolkit (``agent-os``) — policy enforcement, agent identity
     verification, and telemetry as defined by the operator's governance config.

If ``agent-os`` is not installed (e.g. during local development or testing),
the engine falls back gracefully to rule-only evaluation and logs a warning.

Installation::

    pip install agent-os   # not yet on PyPI — check Microsoft AGT release notes

References:
    - Microsoft Agent Governance Toolkit: https://aka.ms/agent-governance (placeholder)
    - CLAUDE.md: "Enforcement engine: Microsoft Agent Governance Toolkit (agent-os)"
"""
from __future__ import annotations

import logging
from typing import Any

from src.rules.models import RuleDefinition, RuleResult
from src.engine.rule_engine import evaluate_rules
from src.finra.provider import LiveDataProvider

logger = logging.getLogger(__name__)

# Attempt to import the Microsoft Agent Governance Toolkit.
# The package name on PyPI will be "agent-os" once released.
try:
    import agent_os  # type: ignore[import-not-found]
    _AGENT_OS_AVAILABLE = True
    logger.info("agent-os (Microsoft Agent Governance Toolkit) loaded successfully.")
except ImportError:
    _AGENT_OS_AVAILABLE = False
    logger.warning(
        "agent-os not installed — governance layer inactive. "
        "Install with: pip install agent-os"
    )


class GovernanceEngine:
    """Two-layer enforcement engine: YAML rule packs + Microsoft AGT.

    The YAML rules run first (sub-millisecond, deterministic).  If all YAML
    rules pass, the request is forwarded to the Agent Governance Toolkit for
    policy enforcement and agent-identity verification.

    If ``agent-os`` is not installed, only the YAML rule layer runs.

    Args:
        rules: Pre-loaded list of :class:`~src.rules.models.RuleDefinition` objects.
        governance_config: Optional dict of AGT configuration passed to
            ``agent_os.GovernanceClient`` (API keys, policy IDs, etc.).
            Must not contain raw secrets — pass via environment variables.
        data_provider: Optional live FINRA/OFAC data provider.  When supplied,
            sanctions and account-status checks use real-time API lookups
            instead of the static stub data in the YAML rule params.
    """

    def __init__(
        self,
        rules: list[RuleDefinition],
        governance_config: dict[str, Any] | None = None,
        data_provider: LiveDataProvider | None = None,
    ) -> None:
        self._rules = rules
        self._governance_config = governance_config or {}
        self._data_provider = data_provider
        self._agt_client: Any = None

        if _AGENT_OS_AVAILABLE:
            self._agt_client = self._init_agt_client()

    def _init_agt_client(self) -> Any:
        """Initialise the Microsoft AGT client.

        Returns:
            A configured ``agent_os.GovernanceClient`` instance, or ``None``
            if initialisation fails.
        """
        try:
            # API shape is illustrative — update when agent-os is published.
            return agent_os.GovernanceClient(**self._governance_config)  # type: ignore[attr-defined]
        except Exception:
            logger.exception("Failed to initialise agent-os GovernanceClient; falling back to rule-only mode.")
            return None

    def evaluate(
        self,
        action_type: str,
        parameters: dict[str, Any],
        context: dict[str, Any],
        agent_id: str,
    ) -> list[RuleResult]:
        """Evaluate an action through all enforcement layers.

        Layer 1 — YAML rules: always run, fast, local.
        Layer 2 — Microsoft AGT: runs only when ``agent-os`` is available and
        all YAML rules pass.  AGT violations are surfaced as additional
        :class:`~src.rules.models.RuleResult` entries.

        Args:
            action_type: Category of action the agent is attempting.
            parameters: Action-specific payload fields.
            context: Ambient metadata available to evaluators.
            agent_id: Identifier of the requesting agent.

        Returns:
            Combined list of :class:`~src.rules.models.RuleResult` from all layers.
        """
        results = evaluate_rules(self._rules, action_type, parameters, context, self._data_provider)

        if not _AGENT_OS_AVAILABLE or self._agt_client is None:
            return results

        # Only forward to AGT when YAML rules pass — fail-fast saves latency.
        if any(not r.passed for r in results):
            return results

        try:
            agt_results = self._evaluate_agt(action_type, parameters, context, agent_id)
            results.extend(agt_results)
        except Exception:
            logger.exception("agent-os evaluation failed; skipping AGT layer.")

        return results

    def _evaluate_agt(
        self,
        action_type: str,
        parameters: dict[str, Any],
        context: dict[str, Any],
        agent_id: str,
    ) -> list[RuleResult]:
        """Invoke the Microsoft AGT policy check and translate results.

        Args:
            action_type: Action being attempted.
            parameters: Action parameters.
            context: Ambient context.
            agent_id: Agent identifier.

        Returns:
            List of :class:`~src.rules.models.RuleResult` translated from AGT response.
        """
        # Illustrative API call — update shape when agent-os is published.
        agt_response = self._agt_client.check_policy(  # type: ignore[union-attr]
            agent_id=agent_id,
            action=action_type,
            payload={**context, **parameters},
        )

        results: list[RuleResult] = []
        for policy_result in getattr(agt_response, "policy_results", []):
            results.append(
                RuleResult(
                    rule_id=f"agt:{policy_result.policy_id}",
                    passed=policy_result.allowed,
                    violation_code=policy_result.violation_code if not policy_result.allowed else None,
                    rationale=policy_result.rationale,
                )
            )
        return results
