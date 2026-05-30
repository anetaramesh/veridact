from __future__ import annotations
import pytest
from src.rules.models import RuleDefinition, CheckType
from src.engine.rule_engine import evaluate_rules


def make_rule(check_type: CheckType, params: dict, vid: str = "VCODE") -> RuleDefinition:
    return RuleDefinition(
        id="test-rule",
        name="Test Rule",
        description="",
        check_type=check_type,
        params=params,
        violation_code=vid,
    )


def test_sanctions_list_blocks_match():
    rule = make_rule(CheckType.sanctions_list, {"field": "recipient_id", "sanctions_list": ["BAD-GUY"]})
    results = evaluate_rules([rule], "transfer", {"recipient_id": "BAD-GUY"}, {})
    assert results[0].passed is False
    assert results[0].violation_code == "VCODE"


def test_sanctions_list_passes_clean():
    rule = make_rule(CheckType.sanctions_list, {"field": "recipient_id", "sanctions_list": ["BAD-GUY"]})
    results = evaluate_rules([rule], "transfer", {"recipient_id": "GOOD-GUY"}, {})
    assert results[0].passed is True


def test_threshold_blocks_over():
    rule = make_rule(CheckType.threshold, {"field": "amount", "max_value": 1000})
    results = evaluate_rules([rule], "transfer", {"amount": 1001}, {})
    assert results[0].passed is False


def test_threshold_passes_at_limit():
    rule = make_rule(CheckType.threshold, {"field": "amount", "max_value": 1000})
    results = evaluate_rules([rule], "transfer", {"amount": 1000}, {})
    assert results[0].passed is True


def test_account_status_blocks_frozen():
    rule = make_rule(CheckType.account_status, {"field": "account_id", "frozen_accounts": ["FROZEN-1"]})
    results = evaluate_rules([rule], "transfer", {"account_id": "FROZEN-1"}, {})
    assert results[0].passed is False


def test_account_status_passes_active():
    rule = make_rule(CheckType.account_status, {"field": "account_id", "frozen_accounts": ["FROZEN-1"]})
    results = evaluate_rules([rule], "transfer", {"account_id": "ACTIVE-1"}, {})
    assert results[0].passed is True


def test_context_fields_available_to_rules():
    """Fields in context should be accessible when not in parameters."""
    rule = make_rule(CheckType.sanctions_list, {"field": "recipient_id", "sanctions_list": ["SDN-CTX"]})
    results = evaluate_rules([rule], "transfer", {}, {"recipient_id": "SDN-CTX"})
    assert results[0].passed is False


def test_parameters_override_context():
    rule = make_rule(CheckType.sanctions_list, {"field": "recipient_id", "sanctions_list": ["SDN-CTX"]})
    # parameters should override context value
    results = evaluate_rules([rule], "transfer", {"recipient_id": "CLEAN"}, {"recipient_id": "SDN-CTX"})
    assert results[0].passed is True
