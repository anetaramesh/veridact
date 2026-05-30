from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from src.engine.models import EvaluationResult, PolicyRule
from src.engine.rule_loader import load_policy_rules
from src.engine.rule_engine import evaluate_rules
from src.rules.models import RuleDefinition, CheckType

logger = logging.getLogger(__name__)

# Attempt to import agent-os; fall back to rule-only mode if the package is
# not yet installed (it is not on PyPI as of the initial release).
try:
    from agent_os import PolicyEngine as _AGTPolicyEngine  # type: ignore[import]

    _AGT_AVAILABLE = True
except ImportError:
    _AGTPolicyEngine = None
    _AGT_AVAILABLE = False
    logger.info("agent-os not installed; AGTAdapter running in rule-only mode.")


_BLOCK_ALL_RESULT = EvaluationResult(
    approved=False,
    violations=["INTERNAL_ERROR"],
    rationale="Evaluation failed with an internal error; request blocked as a fail-safe.",
    latency_ms=0.0,
)


class AGTAdapter:
    """Wraps Microsoft's agent-os PolicyEngine with Veridact's evaluation API.

    When agent-os is installed, evaluation is delegated to
    ``PolicyEngine.evaluate()`` and the result is mapped to
    :class:`~src.engine.models.EvaluationResult`.  When agent-os is absent,
    the adapter falls back to Veridact's built-in rule engine so that tests
    and development environments work without the external dependency.

    Any uncaught exception from the underlying evaluator causes the adapter to
    return a ``hard_block`` fail-safe result rather than propagating the error.

    Args:
        rules_dir: Path to the directory containing ``*.yaml`` rule pack files.

    Raises:
        FileNotFoundError: If *rules_dir* does not exist.
        pydantic.ValidationError: If any YAML file contains an invalid schema.
    """

    def __init__(self, rules_dir: str | Path) -> None:
        self._rules: list[PolicyRule] = load_policy_rules(rules_dir)
        self._agt_engine = _AGTPolicyEngine() if _AGT_AVAILABLE else None
        logger.info(
            "AGTAdapter initialised with %d rules (agent-os=%s).",
            len(self._rules),
            _AGT_AVAILABLE,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        action_type: str,
        parameters: dict[str, Any],
        context: dict[str, Any],
        agent_id: str,
    ) -> EvaluationResult:
        """Evaluate an agent action against all loaded policy rules.

        Args:
            action_type: The action the agent is attempting (e.g. ``"wire_transfer"``).
            parameters: Agent-supplied parameters for the action.
            context: Ambient context — account metadata, session info, etc.
            agent_id: Identifier of the agent making the request (used for audit logs).

        Returns:
            :class:`~src.engine.models.EvaluationResult` with the decision,
            any violation codes, a human-readable rationale, and wall-clock
            latency in milliseconds.
        """
        start = time.perf_counter()
        try:
            result = self._evaluate_inner(action_type, parameters, context, agent_id)
        except Exception:
            logger.exception(
                "Unhandled exception during evaluation for agent=%s action=%s; returning fail-safe block.",
                agent_id,
                action_type,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            return EvaluationResult(
                approved=_BLOCK_ALL_RESULT.approved,
                violations=_BLOCK_ALL_RESULT.violations,
                rationale=_BLOCK_ALL_RESULT.rationale,
                latency_ms=round(elapsed_ms, 3),
            )

        elapsed_ms = (time.perf_counter() - start) * 1000
        return EvaluationResult(
            approved=result.approved,
            violations=result.violations,
            rationale=result.rationale,
            latency_ms=round(elapsed_ms, 3),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_inner(
        self,
        action_type: str,
        parameters: dict[str, Any],
        context: dict[str, Any],
        agent_id: str,
    ) -> EvaluationResult:
        """Dispatch to agent-os or the built-in rule engine."""
        applicable = self._applicable_rules(action_type)

        if self._agt_engine is not None:
            return self._evaluate_via_agt(applicable, action_type, parameters, context, agent_id)

        return self._evaluate_via_rules(applicable, action_type, parameters, context)

    def _applicable_rules(self, action_type: str) -> list[PolicyRule]:
        """Return rules whose ``action_types`` include *action_type* or ``"*"``."""
        return [
            r for r in self._rules
            if "*" in r.action_types or action_type in r.action_types
        ]

    def _evaluate_via_agt(
        self,
        rules: list[PolicyRule],
        action_type: str,
        parameters: dict[str, Any],
        context: dict[str, Any],
        agent_id: str,
    ) -> EvaluationResult:
        """Delegate to agent-os PolicyEngine and map the result."""
        agt_result = self._agt_engine.evaluate(
            agent_id=agent_id,
            action_type=action_type,
            parameters=parameters,
            context=context,
            policy_rules=[r.model_dump() for r in rules],
        )

        violations: list[str] = [v.code for v in getattr(agt_result, "violations", [])]
        approved: bool = getattr(agt_result, "approved", not violations)
        rationale: str = getattr(agt_result, "rationale", self._build_rationale(approved, violations))

        return EvaluationResult(
            approved=approved,
            violations=violations,
            rationale=rationale,
            latency_ms=0.0,  # replaced by caller with wall-clock time
        )

    def _evaluate_via_rules(
        self,
        rules: list[PolicyRule],
        action_type: str,
        parameters: dict[str, Any],
        context: dict[str, Any],
    ) -> EvaluationResult:
        """Run Veridact's built-in rule engine (rule-only fallback)."""
        # Convert PolicyRule → RuleDefinition for the existing engine
        base_rules: list[RuleDefinition] = [
            RuleDefinition(
                id=r.id,
                name=r.name,
                description=r.description,
                check_type=r.check_type,
                params=r.params,
                violation_code=r.violation_code,
            )
            for r in rules
        ]

        rule_results = evaluate_rules(base_rules, action_type, parameters, context)

        violations = [rr.violation_code for rr in rule_results if not rr.passed and rr.violation_code]
        approved = len(violations) == 0
        rationale = self._build_rationale(approved, violations)

        return EvaluationResult(
            approved=approved,
            violations=violations,
            rationale=rationale,
            latency_ms=0.0,  # replaced by caller
        )

    @staticmethod
    def _build_rationale(approved: bool, violations: list[str]) -> str:
        if approved:
            return "All policy checks passed; action approved."
        return f"Action blocked — {len(violations)} violation(s): {', '.join(violations)}."
