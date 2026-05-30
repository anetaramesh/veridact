from __future__ import annotations

import logging
import re
from typing import Any, Callable, TYPE_CHECKING

from src.rules.models import CheckType, RuleDefinition, RuleResult

if TYPE_CHECKING:
    from src.finra.provider import LiveDataProvider

logger = logging.getLogger(__name__)


def _check_sanctions_list(
    rule: RuleDefinition,
    parameters: dict[str, Any],
    data_provider: "LiveDataProvider | None" = None,
) -> RuleResult:
    """Evaluate a sanctions-list rule.

    When a *data_provider* is supplied, the OFAC SDN check is performed via
    the live FINRA/OFAC API rather than the static ``sanctions_list`` in the
    rule's YAML params.  The static list is used as a fallback when no
    provider is configured.

    Args:
        rule: The rule definition providing ``field`` and optional ``sanctions_list`` params.
        parameters: Merged request parameters and context.
        data_provider: Optional live data provider for real-time OFAC screening.

    Returns:
        :class:`~src.rules.models.RuleResult` indicating pass or fail.
    """
    field: str = rule.params.get("field", "recipient_id")
    value: str = str(parameters.get(field, ""))

    if data_provider is not None:
        matched = data_provider.is_sanctioned(value)
    else:
        sanctions: list[str] = rule.params.get("sanctions_list", [])
        matched = value in sanctions

    if matched:
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


def _check_threshold(
    rule: RuleDefinition,
    parameters: dict[str, Any],
    data_provider: "LiveDataProvider | None" = None,
) -> RuleResult:
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
    # Use live threshold from provider if available; fall back to YAML param
    if data_provider is not None:
        max_value: float = data_provider.get_wire_threshold()
    else:
        max_value = rule.params.get("max_value", 0)
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


def _check_account_status(
    rule: RuleDefinition,
    parameters: dict[str, Any],
    data_provider: "LiveDataProvider | None" = None,
) -> RuleResult:
    """Evaluate an account-freeze rule.

    When a *data_provider* is supplied, the account restriction check is
    performed via a live FINRA BrokerCheck lookup rather than the static
    ``frozen_accounts`` list in the rule's YAML params.

    Args:
        rule: The rule definition providing ``field`` and optional ``frozen_accounts`` params.
        parameters: Merged request parameters and context.
        data_provider: Optional live data provider for real-time BrokerCheck lookup.

    Returns:
        :class:`~src.rules.models.RuleResult` indicating pass or fail.
    """
    field: str = rule.params.get("field", "account_id")
    value: str = str(parameters.get(field, ""))

    if data_provider is not None:
        is_frozen = data_provider.is_account_restricted(value)
    else:
        frozen_accounts: list[str] = rule.params.get("frozen_accounts", [])
        is_frozen = value in frozen_accounts

    if is_frozen:
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


def _check_pattern_match(
    rule: RuleDefinition,
    parameters: dict[str, Any],
    data_provider: "LiveDataProvider | None" = None,
) -> RuleResult:
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


def _check_required_fields(
    rule: RuleDefinition,
    parameters: dict[str, Any],
    data_provider: "LiveDataProvider | None" = None,
) -> RuleResult:
    """Evaluate a required-fields rule (FINRA Rule 2090 KYC).

    Blocks the request if any field listed in ``params.required`` is absent
    or empty in the merged parameters.

    Args:
        rule: The rule definition providing a ``required`` list of field names.
        parameters: Merged request parameters and context.

    Returns:
        :class:`~src.rules.models.RuleResult` indicating pass or fail.
    """
    required: list[str] = rule.params.get("required", [])
    missing = [f for f in required if not str(parameters.get(f, "")).strip()]

    if missing:
        logger.warning(
            "KYC missing fields: rule=%s missing=%s", rule.id, missing
        )
        return RuleResult(
            rule_id=rule.id,
            passed=False,
            violation_code=rule.violation_code,
            rationale=f"Required KYC fields missing or empty: {', '.join(missing)}.",
        )
    return RuleResult(
        rule_id=rule.id,
        passed=True,
        rationale=f"All required KYC fields present: {', '.join(required)}.",
    )


# Registry mapping each CheckType to its evaluator function.
_CHECKERS: dict[CheckType, Callable[..., RuleResult]] = {
    CheckType.sanctions_list: _check_sanctions_list,
    CheckType.threshold: _check_threshold,
    CheckType.account_status: _check_account_status,
    CheckType.pattern_match: _check_pattern_match,
    CheckType.required_fields: _check_required_fields,
}


def evaluate_rules(
    rules: list[RuleDefinition],
    action_type: str,
    parameters: dict[str, Any],
    context: dict[str, Any],
    data_provider: "LiveDataProvider | None" = None,
) -> list[RuleResult]:
    """Run every rule against the supplied request and return one result per rule.

    When *data_provider* is supplied, ``sanctions_list``, ``account_status``,
    and ``threshold`` checks are resolved via live FINRA/OFAC API calls instead
    of the static stub data in the rule's YAML params.

    Args:
        rules: Ordered list of rules to evaluate.
        action_type: The action the agent is attempting (e.g. ``"wire_transfer"``).
        parameters: Agent-supplied parameters for the action.
        context: Additional ambient context (account metadata, session info, etc.).
        data_provider: Optional live FINRA/OFAC data provider.

    Returns:
        List of :class:`~src.rules.models.RuleResult`, one per rule, in the same order.
    """
    merged: dict[str, Any] = {**context, **parameters}
    results: list[RuleResult] = []

    for rule in rules:
        if "*" not in rule.action_types and action_type not in rule.action_types:
            continue
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
            results.append(checker(rule, merged, data_provider))

    return results
