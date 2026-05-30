"""Tests for finra_wire_threshold rule.

Rule: finra_wire_threshold
Regulation: FINRA Rule 3110(a); BSA 31 U.S.C. § 5318(g); 31 C.F.R. § 1010.410
Check type: threshold  —  blocks wire_transfer when amount > $1,000,000 USD.
Severity: soft_hold

The AGT PolicyEngine is mocked so we exercise Veridact's rule logic only,
not AGT internals.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.engine.agt_adapter import AGTAdapter
from src.engine.models import EvaluationResult


RULES_DIR = Path(__file__).parent.parent.parent / "rules"
RULE_ID = "finra_wire_threshold"
VIOLATION_CODE = "WIRE_THRESHOLD_EXCEEDED"


@pytest.fixture()
def adapter(monkeypatch: pytest.MonkeyPatch) -> AGTAdapter:
    """AGTAdapter backed by the real rule YAML with AGT engine mocked out."""
    monkeypatch.setattr("src.engine.agt_adapter._AGT_AVAILABLE", False)
    monkeypatch.setattr("src.engine.agt_adapter._AGTPolicyEngine", None)
    return AGTAdapter(rules_dir=RULES_DIR)


# ---------------------------------------------------------------------------
# Passes — valid actions that must be approved
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("amount", [0, 1, 999_999, 1_000_000])
def test_finra_wire_threshold_passes_valid_action(
    adapter: AGTAdapter, amount: int
) -> None:
    """Wire transfers at or below $1,000,000 must be approved."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"recipient_id": "CLEAN-BANK", "amount": amount, "customer_id": "CUST-001", "account_id": "ACC-001"},
        context={"account_id": "ACC-ACTIVE-1"},
        agent_id="agent-test",
    )
    assert result.approved is True
    assert VIOLATION_CODE not in result.violations


# ---------------------------------------------------------------------------
# Blocks — amounts that exceed the threshold
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("amount", [1_000_001, 1_500_000, 10_000_000])
def test_finra_wire_threshold_blocks_violation(
    adapter: AGTAdapter, amount: int
) -> None:
    """Wire transfers above $1,000,000 must be blocked with WIRE_THRESHOLD_EXCEEDED."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"recipient_id": "CLEAN-BANK", "amount": amount, "customer_id": "CUST-001", "account_id": "ACC-001"},
        context={"account_id": "ACC-ACTIVE-1"},
        agent_id="agent-test",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations


# ---------------------------------------------------------------------------
# Edge cases / boundary values
# ---------------------------------------------------------------------------

def test_finra_wire_threshold_edge_case_boundary_value_at_limit(
    adapter: AGTAdapter,
) -> None:
    """Amount exactly equal to max_value ($1,000,000) must pass (non-strict inequality)."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"recipient_id": "CLEAN-BANK", "amount": 1_000_000, "customer_id": "CUST-001", "account_id": "ACC-001"},
        context={},
        agent_id="agent-boundary",
    )
    assert result.approved is True
    assert VIOLATION_CODE not in result.violations


def test_finra_wire_threshold_edge_case_boundary_value_one_over(
    adapter: AGTAdapter, over_threshold_amount: int
) -> None:
    """Amount $1,000,001 (conftest fixture) must trigger the threshold rule."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"recipient_id": "CLEAN-BANK", "amount": over_threshold_amount, "customer_id": "CUST-001", "account_id": "ACC-001"},
        context={},
        agent_id="agent-boundary",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations


def test_finra_wire_threshold_does_not_apply_to_non_wire_actions(
    adapter: AGTAdapter, over_threshold_amount: int
) -> None:
    """Threshold rule is scoped to wire_transfer only; equity_trade must not be blocked."""
    result = adapter.evaluate(
        action_type="equity_trade",
        parameters={"amount": over_threshold_amount},
        context={},
        agent_id="agent-scoping",
    )
    assert VIOLATION_CODE not in result.violations


def test_finra_wire_threshold_amount_in_context(adapter: AGTAdapter) -> None:
    """Amount supplied via context (not parameters) must still trigger the rule."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"recipient_id": "CLEAN-BANK"},
        context={"amount": 2_000_000},
        agent_id="agent-ctx",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations
