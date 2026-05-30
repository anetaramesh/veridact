"""Tests for the GovernanceEngine (src/engine/governance.py).

agent-os is not available in test environments, so all tests exercise the
graceful fallback path (rule-only evaluation).  AGT integration tests are
marked with ``@pytest.mark.agt`` and skipped unless agent-os is installed.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.engine.governance import GovernanceEngine, _AGENT_OS_AVAILABLE
from src.rules.models import CheckType, RuleDefinition, RuleResult


def _make_rules() -> list[RuleDefinition]:
    return [
        RuleDefinition(
            id="test-threshold",
            name="Test Threshold",
            description="Blocks amount > 1000",
            check_type=CheckType.threshold,
            params={"field": "amount", "max_value": 1000},
            violation_code="THRESHOLD_EXCEEDED",
        ),
        RuleDefinition(
            id="test-sanctions",
            name="Test Sanctions",
            description="Blocks SDN matches",
            check_type=CheckType.sanctions_list,
            params={"field": "recipient_id", "sanctions_list": ["BAD-GUY"]},
            violation_code="SANCTIONS_MATCH",
        ),
    ]


# ---------------------------------------------------------------------------
# Fallback (no agent-os) behaviour
# ---------------------------------------------------------------------------


def test_governance_engine_initialises_without_agent_os() -> None:
    engine = GovernanceEngine(rules=_make_rules())
    assert engine is not None


def test_evaluate_passes_clean_request() -> None:
    engine = GovernanceEngine(rules=_make_rules())
    results = engine.evaluate("wire_transfer", {"amount": 100, "recipient_id": "CLEAN"}, {}, "agent-1")
    assert all(r.passed for r in results)


def test_evaluate_blocks_threshold_violation() -> None:
    engine = GovernanceEngine(rules=_make_rules())
    results = engine.evaluate("wire_transfer", {"amount": 5000, "recipient_id": "CLEAN"}, {}, "agent-1")
    failed = [r for r in results if not r.passed]
    assert any(r.violation_code == "THRESHOLD_EXCEEDED" for r in failed)


def test_evaluate_blocks_sanctions_violation() -> None:
    engine = GovernanceEngine(rules=_make_rules())
    results = engine.evaluate("wire_transfer", {"amount": 50, "recipient_id": "BAD-GUY"}, {}, "agent-1")
    failed = [r for r in results if not r.passed]
    assert any(r.violation_code == "SANCTIONS_MATCH" for r in failed)


def test_evaluate_returns_one_result_per_rule() -> None:
    rules = _make_rules()
    engine = GovernanceEngine(rules=rules)
    results = engine.evaluate("wire_transfer", {"amount": 50, "recipient_id": "CLEAN"}, {}, "agent-1")
    assert len(results) == len(rules)


def test_evaluate_context_fields_accessible() -> None:
    engine = GovernanceEngine(rules=_make_rules())
    # recipient_id supplied via context, not parameters
    results = engine.evaluate("wire_transfer", {"amount": 50}, {"recipient_id": "BAD-GUY"}, "agent-1")
    failed = [r for r in results if not r.passed]
    assert any(r.violation_code == "SANCTIONS_MATCH" for r in failed)


def test_evaluate_parameters_override_context() -> None:
    engine = GovernanceEngine(rules=_make_rules())
    results = engine.evaluate(
        "wire_transfer",
        {"amount": 50, "recipient_id": "CLEAN"},
        {"recipient_id": "BAD-GUY"},
        "agent-1",
    )
    assert all(r.passed for r in results)


def test_empty_rules_list_returns_empty_results() -> None:
    engine = GovernanceEngine(rules=[])
    results = engine.evaluate("wire_transfer", {"amount": 100}, {}, "agent-1")
    assert results == []


# ---------------------------------------------------------------------------
# AGT layer (mocked)
# ---------------------------------------------------------------------------


def test_agt_layer_not_called_when_yaml_rules_fail() -> None:
    """AGT should be skipped when YAML rules already block the request."""
    engine = GovernanceEngine(rules=_make_rules())
    engine._agt_client = MagicMock()

    engine.evaluate("wire_transfer", {"amount": 99999, "recipient_id": "CLEAN"}, {}, "agent-1")

    engine._agt_client.check_policy.assert_not_called()


def test_agt_layer_called_when_yaml_rules_pass() -> None:
    """AGT should be invoked when all YAML rules pass."""
    engine = GovernanceEngine(rules=_make_rules())

    mock_response = MagicMock()
    mock_response.policy_results = []
    mock_client = MagicMock()
    mock_client.check_policy.return_value = mock_response
    engine._agt_client = mock_client

    with patch("src.engine.governance._AGENT_OS_AVAILABLE", True):
        engine.evaluate("wire_transfer", {"amount": 50, "recipient_id": "CLEAN"}, {}, "agent-1")

    mock_client.check_policy.assert_called_once()


def test_agt_violation_surfaces_as_rule_result() -> None:
    """AGT policy violations should appear as RuleResult entries."""
    engine = GovernanceEngine(rules=_make_rules())

    policy_result = MagicMock()
    policy_result.policy_id = "agt-policy-001"
    policy_result.allowed = False
    policy_result.violation_code = "AGT_POLICY_VIOLATION"
    policy_result.rationale = "Blocked by AGT policy."

    mock_response = MagicMock()
    mock_response.policy_results = [policy_result]
    mock_client = MagicMock()
    mock_client.check_policy.return_value = mock_response
    engine._agt_client = mock_client

    with patch("src.engine.governance._AGENT_OS_AVAILABLE", True):
        results = engine.evaluate("wire_transfer", {"amount": 50, "recipient_id": "CLEAN"}, {}, "agent-1")

    agt_results = [r for r in results if r.rule_id.startswith("agt:")]
    assert len(agt_results) == 1
    assert agt_results[0].passed is False
    assert agt_results[0].violation_code == "AGT_POLICY_VIOLATION"


def test_agt_exception_does_not_crash_evaluation() -> None:
    """An AGT failure should be swallowed; YAML results still returned."""
    engine = GovernanceEngine(rules=_make_rules())
    mock_client = MagicMock()
    mock_client.check_policy.side_effect = RuntimeError("AGT timeout")
    engine._agt_client = mock_client

    with patch("src.engine.governance._AGENT_OS_AVAILABLE", True):
        results = engine.evaluate("wire_transfer", {"amount": 50, "recipient_id": "CLEAN"}, {}, "agent-1")

    # Should still get YAML results, no crash
    assert len(results) == len(_make_rules())
