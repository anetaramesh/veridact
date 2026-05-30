from __future__ import annotations

import logging
import re
from typing import Any, Callable

from src.rules.models import CheckType, RuleDefinition, RuleResult

logger = logging.getLogger(__name__)


def _check_sanctions_list(rule: RuleDefinition, parameters: dict[str, Any]) -> RuleResult:
    """Evaluate a sanctions-list rule.

    Blocks the request if the value of ``params.field`` appears in
    ``params.sanctions_list``.

    Args:
        rule: The rule definition providing ``field`` and ``sanctions_list`` params.
        parameters: Merged request parameters and context.

    Returns:
        :class:`~src.rules.models.RuleResult` indicating pass or fail.
    """
    sanctions: list[str] = rule.params.get("sanctions_list", [])
    field: str = rule.params.get("field", "recipient_id")
    value: str = str(parameters.get(field, ""))

    if value in sanctions:
        logger.warning("Sanctions match: rule=%s field=%s value=%s", rule.id, field, value)
        return RuleResult(
            rule_id=rule.id,
            passed=False,
            violation_code=rule.violation_code,
            rationale=f"Field '{field}' value '{value}' is on the OFAC sanctions list.",
        )
    return RuleResult(
        rule_id=rule.id,
        passed=True,
        rationale=f"'{value}' not on sanctions list.",
    )


def _check_threshold(rule: RuleDefinition, parameters: dict[str, Any]) -> RuleResult:
    """Evaluate a numeric threshold rule.

    Blocks the request if the numeric value of ``params.field`` strictly
    exceeds ``params.max_value``.

    Args:
        rule: The rule definition providing ``field`` and ``max_value`` params.
        parameters: Merged request parameters and context.

    Returns:
        :class:`~src.rules.models.RuleResult` indicating pass or fail.
    """
    field: str = rule.params.get("field", "amount")
    max_value: float = rule.params.get("max_value", 0)
    raw = parameters.get(field, 0)

    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.0

    if value > max_value:
        logger.warning("Threshold exceeded: rule=%s field=%s value=%s max=%s", rule.id, field, value, max_value)
        return RuleResult(
            rule_id=rule.id,
            passed=False,
            violation_code=rule.violation_code,
            rationale=f"'{field}' value {value} exceeds threshold of {max_value}.",
        )
    return RuleResult(
        rule_id=rule.id,
        passed=True,
        rationale=f"'{field}' value {value} within threshold.",
    )


def _check_account_status(rule: RuleDefinition, parameters: dict[str, Any]) -> RuleResult:
    """Evaluate an account-freeze rule.

    Blocks the request if the value of ``params.field`` appears in the
    ``params.frozen_accounts`` list.

    Args:
        rule: The rule definition providing ``field`` and ``frozen_accounts`` params.
        parameters: Merged request parameters and context.

    Returns:
        :class:`~src.rules.models.RuleResult` indicating pass or fail.
    """
    frozen_accounts: list[str] = rule.params.get("frozen_accounts", [])
    field: str = rule.params.get("field", "account_id")
    value: str = str(parameters.get(field, ""))

    if value in frozen_accounts:
        logger.warning("Frozen account: rule=%s field=%s value=%s", rule.id, field, value)
        return RuleResult(
            rule_id=rule.id,
            passed=False,
            violation_code=rule.violation_code,
            rationale=f"Account '{value}' is frozen and cannot be used.",
        )
    return RuleResult(
        rule_id=rule.id,
        passed=True,
        rationale=f"Account '{value}' is in good standing.",
    )


def _check_pattern_match(rule: RuleDefinition, parameters: dict[str, Any]) -> RuleResult:
    """Evaluate a regex pattern-match rule.

    Blocks the request if the value of ``params.field`` matches the
    ``params.pattern`` regular expression.

    Args:
        rule: The rule definition providing ``field`` and ``pattern`` params.
        parameters: Merged request parameters and context.

    Returns:
        :class:`~src.rules.models.RuleResult` indicating pass or fail.
    """
    field: str = rule.params.get("field", "")
    pattern: str = rule.params.get("pattern", "")
    value: str = str(parameters.get(field, ""))

    try:
        matched = bool(re.search(pattern, value))
    except re.error as exc:
        logger.error("Invalid regex in rule %s: %s", rule.id, exc)
        matched = False

    if matched:
        logger.warning("Pattern match: rule=%s field=%s value=%s pattern=%s", rule.id, field, value, pattern)
        return RuleResult(
            rule_id=rule.id,
            passed=False,
            violation_code=rule.violation_code,
            rationale=f"Field '{field}' value '{value}' matched pattern '{pattern}'.",
        )
    return RuleResult(
        rule_id=rule.id,
        passed=True,
        rationale=f"Field '{field}' value '{value}' did not match pattern.",
    )


# Registry mapping each CheckType to its evaluator function.
_CHECKERS: dict[CheckType, Callable[[RuleDefinition, dict[str, Any]], RuleResult]] = {
    CheckType.sanctions_list: _check_sanctions_list,
    CheckType.threshold: _check_threshold,
    CheckType.account_status: _check_account_status,
    CheckType.pattern_match: _check_pattern_match,
}


def evaluate_rules(
    rules: list[RuleDefinition],
    action_type: str,
    parameters: dict[str, Any],
    context: dict[str, Any],
) -> list[RuleResult]:
    """Run every rule against the supplied request and return one result per rule.

    Context fields are available as fallback values; ``parameters`` fields take
    precedence over identically-named ``context`` fields.

    Args:
        rules: Ordered list of rules to evaluate.
        action_type: The action the agent is attempting (e.g. ``"wire_transfer"``).
        parameters: Agent-supplied parameters for the action.
        context: Additional ambient context (account metadata, session info, etc.).

    Returns:
        List of :class:`~src.rules.models.RuleResult`, one per rule, in the same order.
    """
    # Parameters override context for field lookups
    merged: dict[str, Any] = {**context, **parameters}
    results: list[RuleResult] = []

    for rule in rules:
        checker = _CHECKERS.get(rule.check_type)
        if checker is None:
            logger.error("Unknown check_type '%s' in rule '%s'; skipping.", rule.check_type, rule.id)
            results.append(
                RuleResult(
                    rule_id=rule.id,
                    passed=True,
                    rationale=f"Unknown check_type '{rule.check_type}'; skipped.",
                )
            )
        else:
            results.append(checker(rule, merged))

    return results
