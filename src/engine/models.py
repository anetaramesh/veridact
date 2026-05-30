from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel

from src.rules.models import CheckType


class Severity(str, Enum):
    """How hard the system should enforce a rule violation."""

    hard_block = "hard_block"
    soft_hold = "soft_hold"
    flag = "flag"


class PolicyRule(BaseModel):
    """Extended rule schema used by the AGT adapter layer.

    Adds regulation citation, action scoping, severity, and a rationale
    template on top of the base :class:`~src.rules.models.RuleDefinition`.

    Attributes:
        id: Unique machine-readable rule identifier (e.g. ``"finra_ofac_001"``).
        name: Human-readable rule name shown in violation reports.
        regulation_ref: Precise regulatory citation (e.g. ``"FINRA Rule 3110(a)"``).
        description: Full description including regulatory context.
        check_type: Evaluation strategy; must be a valid ``CheckType``.
        action_types: Action types this rule applies to; ``["*"]`` means all.
        params: Strategy-specific parameters (e.g. ``sanctions_list``, ``max_value``).
        violation_code: Short code emitted when the rule fails.
        severity: Enforcement level — ``hard_block``, ``soft_hold``, or ``flag``.
        rationale_template: Plain-English template; use ``{field}`` for substitution.
    """

    id: str
    name: str
    regulation_ref: str
    description: str
    check_type: CheckType
    action_types: list[str]
    params: dict[str, Any]
    violation_code: str
    severity: Severity
    rationale_template: str


class EvaluationResult(BaseModel):
    """Outcome returned by :func:`~src.engine.agt_adapter.AGTAdapter.evaluate`.

    Attributes:
        approved: ``True`` if the action is permitted to proceed.
        violations: List of violation codes from rules that fired.
        rationale: Human-readable explanation of the overall decision.
        latency_ms: Wall-clock evaluation time in milliseconds.
    """

    approved: bool
    violations: list[str]
    rationale: str
    latency_ms: float
