from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel


class CheckType(str, Enum):
    """Supported rule evaluation strategies."""

    sanctions_list = "sanctions_list"
    threshold = "threshold"
    account_status = "account_status"
    pattern_match = "pattern_match"


class RuleDefinition(BaseModel):
    """Schema for a single compliance rule loaded from a YAML rule pack.

    Attributes:
        id: Unique machine-readable rule identifier.
        name: Human-readable rule name shown in violation reports.
        description: Full description including regulatory citation.
        check_type: Evaluation strategy; must be a valid ``CheckType``.
        params: Strategy-specific parameters (e.g. ``sanctions_list``, ``max_value``).
        violation_code: Short code emitted when the rule fails (e.g. ``OFAC_SANCTIONS_MATCH``).
    """

    id: str
    name: str
    description: str
    check_type: CheckType
    params: dict[str, Any]
    violation_code: str


class RuleResult(BaseModel):
    """Outcome of evaluating one rule against a single request.

    Attributes:
        rule_id: ID of the rule that produced this result.
        passed: ``True`` if the request satisfies the rule.
        violation_code: Populated only when ``passed`` is ``False``.
        rationale: Human-readable explanation of the outcome.
    """

    rule_id: str
    passed: bool
    violation_code: str | None = None
    rationale: str
