"""Tests for finra_account_freeze rule.

Rule: finra_account_freeze
Regulation: FINRA Rule 4511; SEC Rule 17a-3 (17 C.F.R. § 240.17a-3); SEA § 15(b)(4)(E)
Check type: account_status  —  action_types: ["*"] (applies to ALL action types).
Severity: hard_block

The AGT PolicyEngine and FINRA live data provider are both mocked so we
exercise Veridact's rule logic only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.engine.agt_adapter import AGTAdapter
from src.finra.provider import LiveDataProvider


RULES_DIR = Path(__file__).parent.parent.parent / "rules"
RULE_ID = "finra_account_freeze"
VIOLATION_CODE = "ACCOUNT_FROZEN"

FROZEN_ACCOUNT_IDS = ["FROZEN-ACC-001", "FROZEN-ACC-002", "FROZEN-ACC-003"]

SAMPLED_ACTION_TYPES = [
    "wire_transfer",
    "equity_trade",
    "ach_payment",
    "loan_decision",
    "check_issuance",
    "internal_transfer",
]


class _MockDataProvider:
    """Stub LiveDataProvider that mirrors the old YAML frozen-accounts list."""

    def is_sanctioned(self, entity_id: str) -> bool:
        return False

    def is_account_restricted(self, account_id: str) -> bool:
        return account_id in FROZEN_ACCOUNT_IDS

    def get_wire_threshold(self) -> float:
        return 1_000_000.0


@pytest.fixture()
def adapter(monkeypatch: pytest.MonkeyPatch) -> AGTAdapter:
    """AGTAdapter backed by the real rule YAML with AGT engine and FINRA API mocked."""
    monkeypatch.setattr("src.engine.agt_adapter._AGT_AVAILABLE", False)
    monkeypatch.setattr("src.engine.agt_adapter._AGTPolicyEngine", None)
    return AGTAdapter(rules_dir=RULES_DIR, data_provider=_MockDataProvider())


# ---------------------------------------------------------------------------
# Passes — active (non-frozen) accounts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action_type", SAMPLED_ACTION_TYPES)
def test_finra_account_freeze_passes_valid_action(
    adapter: AGTAdapter, action_type: str
) -> None:
    """Transactions on active accounts must be approved for any action type."""
    result = adapter.evaluate(
        action_type=action_type,
        parameters={"amount": 1000, "customer_id": "CUST-001", "account_id": "ACC-ACTIVE-42",
                    "date_of_birth": "1980-01-01", "investment_objective": "growth"},
        context={},
        agent_id="agent-test",
    )
    assert result.approved is True
    assert VIOLATION_CODE not in result.violations


# ---------------------------------------------------------------------------
# Blocks — every frozen account ID across a range of action types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action_type", SAMPLED_ACTION_TYPES)
@pytest.mark.parametrize("frozen_id", FROZEN_ACCOUNT_IDS)
def test_finra_account_freeze_blocks_violation(
    adapter: AGTAdapter, action_type: str, frozen_id: str
) -> None:
    """Every frozen account must be blocked regardless of action type."""
    result = adapter.evaluate(
        action_type=action_type,
        parameters={"amount": 100, "customer_id": "CUST-001", "account_id": frozen_id},
        context={},
        agent_id="agent-test",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations


# ---------------------------------------------------------------------------
# Edge cases / boundary values
# ---------------------------------------------------------------------------

def test_finra_account_freeze_edge_case_boundary_value_partial_id(
    adapter: AGTAdapter,
) -> None:
    """A substring of a frozen account ID ('FROZEN-ACC') must not trigger the rule."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"customer_id": "CUST-001", "account_id": "FROZEN-ACC"},
        context={},
        agent_id="agent-boundary",
    )
    assert VIOLATION_CODE not in result.violations


def test_finra_account_freeze_edge_case_boundary_value_account_in_context(
    adapter: AGTAdapter,
) -> None:
    """Frozen account_id in context (not parameters) must still be blocked."""
    result = adapter.evaluate(
        action_type="equity_trade",
        parameters={"ticker": "GOOG", "customer_id": "CUST-001"},
        context={"account_id": "FROZEN-ACC-001"},
        agent_id="agent-boundary",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations


def test_finra_account_freeze_edge_case_boundary_value_parameters_override_context(
    adapter: AGTAdapter,
) -> None:
    """Active account_id in parameters must override frozen account_id in context."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"customer_id": "CUST-001", "account_id": "ACC-ACTIVE-99"},
        context={"account_id": "FROZEN-ACC-002"},
        agent_id="agent-boundary",
    )
    assert result.approved is True
    assert VIOLATION_CODE not in result.violations


def test_finra_account_freeze_blocks_wire_transfer_on_frozen_account(
    adapter: AGTAdapter,
) -> None:
    """Wildcard rule must block a wire transfer on a frozen account."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={
            "customer_id": "CUST-001",
            "account_id": "FROZEN-ACC-003",
            "recipient_id": "LEGIT-BANK",
            "amount": 500,
        },
        context={},
        agent_id="agent-test",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations
