"""Tests for YAML rule loading and policy-rule evaluation (no real AGT calls)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.engine.models import EvaluationResult, PolicyRule, Severity
from src.engine.rule_loader import load_policy_rules
from src.engine.agt_adapter import AGTAdapter
from src.rules.models import CheckType


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def rules_dir() -> Path:
    """Return the path to the project's real rules directory."""
    return Path(__file__).parent.parent / "rules"


@pytest.fixture()
def sanctions_rule() -> PolicyRule:
    return PolicyRule(
        id="finra_ofac_sanctions",
        name="OFAC Sanctions Check",
        regulation_ref="FINRA Rule 3310; BSA 31 U.S.C. § 5318(l)",
        description="Blocks wire transfers to sanctioned recipients.",
        check_type=CheckType.sanctions_list,
        action_types=["wire_transfer"],
        params={"field": "recipient_id", "sanctions_list": ["SDN-001", "BLOCKED-ENTITY-A"]},
        violation_code="OFAC_SANCTIONS_MATCH",
        severity=Severity.hard_block,
        rationale_template="Recipient '{recipient_id}' is on the OFAC SDN list.",
    )


@pytest.fixture()
def threshold_rule() -> PolicyRule:
    return PolicyRule(
        id="finra_wire_threshold",
        name="Large Wire Transfer Threshold",
        regulation_ref="FINRA Rule 3110(a); BSA 31 U.S.C. § 5318(g)",
        description="Blocks autonomous wire transfers over $1,000,000.",
        check_type=CheckType.threshold,
        action_types=["wire_transfer"],
        params={"field": "amount", "max_value": 1_000_000},
        violation_code="WIRE_THRESHOLD_EXCEEDED",
        severity=Severity.soft_hold,
        rationale_template="Amount ${amount} exceeds the $1,000,000 autonomous-execution limit.",
    )


@pytest.fixture()
def tmp_rules_dir(tmp_path: Path, sanctions_rule: PolicyRule, threshold_rule: PolicyRule) -> Path:
    """Write two minimal rule YAMLs to a temp directory for loader tests."""
    for rule in (sanctions_rule, threshold_rule):
        # mode='json' serialises enums as plain strings so yaml.safe_load can parse them
        data = rule.model_dump(mode="json")
        (tmp_path / f"{rule.id}.yaml").write_text(yaml.dump(data))
    return tmp_path


@pytest.fixture()
def adapter(tmp_rules_dir: Path) -> AGTAdapter:
    """AGTAdapter pointed at the temp rules directory (no real AGT calls)."""
    return AGTAdapter(rules_dir=tmp_rules_dir)


# ---------------------------------------------------------------------------
# 1. YAML loading
# ---------------------------------------------------------------------------

def test_rule_yaml_loads_correctly(rules_dir: Path) -> None:
    """All YAML files in /rules should load and validate as PolicyRule objects."""
    rules = load_policy_rules(rules_dir)
    assert len(rules) >= 3, "Expected at least 3 FINRA rules"

    ids = {r.id for r in rules}
    assert "finra_ofac_sanctions" in ids
    assert "finra_wire_threshold" in ids
    assert "finra_account_freeze" in ids

    for rule in rules:
        assert rule.id, "Rule must have an id"
        assert rule.regulation_ref, "Rule must cite a regulation"
        assert rule.violation_code, "Rule must have a violation_code"
        assert rule.severity in Severity, "Severity must be a valid enum value"
        assert rule.action_types, "action_types must be non-empty"


def test_rule_loader_skips_template(rules_dir: Path) -> None:
    """TEMPLATE.yaml must not be loaded as a policy rule."""
    rules = load_policy_rules(rules_dir)
    ids = {r.id for r in rules}
    # TEMPLATE.yaml uses id 'finra_example_001' but the loader skips it
    assert "finra_example_001" not in ids


def test_rule_loader_raises_on_missing_dir(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_policy_rules(tmp_path / "nonexistent")


# ---------------------------------------------------------------------------
# 2. Sanctions check
# ---------------------------------------------------------------------------

def test_sanctions_check_blocks_flagged_recipient(adapter: AGTAdapter) -> None:
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"recipient_id": "SDN-001", "amount": 5000},
        context={"account_id": "ACC-CLEAN"},
        agent_id="agent-test-001",
    )
    assert result.approved is False
    assert "OFAC_SANCTIONS_MATCH" in result.violations
    assert result.latency_ms >= 0


def test_sanctions_check_passes_clean_recipient(adapter: AGTAdapter) -> None:
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"recipient_id": "LEGIT-COUNTERPARTY", "amount": 5000},
        context={"account_id": "ACC-CLEAN"},
        agent_id="agent-test-001",
    )
    assert result.approved is True
    assert result.violations == []


# ---------------------------------------------------------------------------
# 3. Threshold check
# ---------------------------------------------------------------------------

def test_threshold_check_blocks_over_limit(adapter: AGTAdapter) -> None:
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"recipient_id": "LEGIT-COUNTERPARTY", "amount": 1_500_000},
        context={"account_id": "ACC-CLEAN"},
        agent_id="agent-test-002",
    )
    assert result.approved is False
    assert "WIRE_THRESHOLD_EXCEEDED" in result.violations


def test_threshold_check_passes_under_limit(adapter: AGTAdapter) -> None:
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"recipient_id": "LEGIT-COUNTERPARTY", "amount": 999_999},
        context={"account_id": "ACC-CLEAN"},
        agent_id="agent-test-002",
    )
    assert result.approved is True
    assert result.violations == []


def test_threshold_check_passes_at_exact_limit(adapter: AGTAdapter) -> None:
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"recipient_id": "LEGIT-COUNTERPARTY", "amount": 1_000_000},
        context={},
        agent_id="agent-test-002",
    )
    assert result.approved is True


# ---------------------------------------------------------------------------
# 4. Action-type scoping
# ---------------------------------------------------------------------------

def test_wire_transfer_rule_does_not_apply_to_other_action_types(
    adapter: AGTAdapter,
) -> None:
    """A rule scoped to wire_transfer must not fire on equity_trade."""
    result = adapter.evaluate(
        action_type="equity_trade",
        parameters={"recipient_id": "SDN-001", "amount": 2_000_000},
        context={},
        agent_id="agent-test-003",
    )
    assert result.approved is True


# ---------------------------------------------------------------------------
# 5. Fail-safe on exception
# ---------------------------------------------------------------------------

def test_evaluate_returns_block_on_internal_error(
    tmp_rules_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AGTAdapter must return approved=False when the inner evaluator raises."""
    adapter = AGTAdapter(rules_dir=tmp_rules_dir)

    def _raise(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise RuntimeError("simulated internal failure")

    monkeypatch.setattr(adapter, "_evaluate_inner", _raise)

    result = adapter.evaluate("wire_transfer", {}, {}, "agent-failsafe")
    assert result.approved is False
    assert "INTERNAL_ERROR" in result.violations
