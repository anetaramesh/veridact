"""Tests for finra_ofac_sanctions rule.

Rule: finra_ofac_sanctions
Regulation: FINRA Rule 3310; BSA 31 U.S.C. § 5318(l); 31 C.F.R. Part 501
Check type: sanctions_list  —  blocks wire_transfer / ach_payment /
            internal_transfer / check_issuance when recipient_id is on the
            OFAC SDN list.
Severity: hard_block

The AGT PolicyEngine and FINRA/OFAC data provider are both mocked so we
exercise Veridact's rule logic only.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.engine.agt_adapter import AGTAdapter


RULES_DIR = Path(__file__).parent.parent.parent / "rules"
RULE_ID = "finra_ofac_sanctions"
VIOLATION_CODE = "OFAC_SANCTIONS_MATCH"

SDN_IDS = ["SDN-001", "SDN-002", "SDN-003", "BLOCKED-ENTITY-A", "BLOCKED-ENTITY-B"]

COVERED_ACTION_TYPES = [
    "wire_transfer",
    "ach_payment",
    "internal_transfer",
    "check_issuance",
]


class _MockDataProvider:
    """Stub LiveDataProvider that mirrors the old YAML SDN list."""

    def is_sanctioned(self, entity_id: str) -> bool:
        return entity_id in SDN_IDS

    def is_account_restricted(self, account_id: str) -> bool:
        return False

    def get_wire_threshold(self) -> float:
        return 1_000_000.0


@pytest.fixture()
def adapter(monkeypatch: pytest.MonkeyPatch) -> AGTAdapter:
    """AGTAdapter backed by the real rule YAML with AGT engine and FINRA API mocked."""
    monkeypatch.setattr("src.engine.agt_adapter._AGT_AVAILABLE", False)
    monkeypatch.setattr("src.engine.agt_adapter._AGTPolicyEngine", None)
    return AGTAdapter(rules_dir=RULES_DIR, data_provider=_MockDataProvider())


# ---------------------------------------------------------------------------
# Passes — clean recipients across all covered action types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action_type", COVERED_ACTION_TYPES)
def test_finra_ofac_sanctions_passes_valid_action(
    adapter: AGTAdapter, action_type: str
) -> None:
    """Clean recipients must be approved for all action types covered by the rule."""
    result = adapter.evaluate(
        action_type=action_type,
        parameters={"recipient_id": "LEGIT-COUNTERPARTY", "amount": 1000, "customer_id": "CUST-001", "account_id": "ACC-001"},
        context={"account_id": "ACC-ACTIVE-1"},
        agent_id="agent-test",
    )
    assert result.approved is True
    assert VIOLATION_CODE not in result.violations


# ---------------------------------------------------------------------------
# Blocks — every SDN entry across all covered action types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action_type", COVERED_ACTION_TYPES)
@pytest.mark.parametrize("sdn_id", SDN_IDS)
def test_finra_ofac_sanctions_blocks_violation(
    adapter: AGTAdapter, action_type: str, sdn_id: str
) -> None:
    """Every SDN entry must be blocked for every covered action type."""
    result = adapter.evaluate(
        action_type=action_type,
        parameters={"recipient_id": sdn_id, "amount": 1000, "customer_id": "CUST-001", "account_id": "ACC-001"},
        context={"account_id": "ACC-ACTIVE-1"},
        agent_id="agent-test",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations


# ---------------------------------------------------------------------------
# Edge cases / boundary values
# ---------------------------------------------------------------------------

def test_finra_ofac_sanctions_edge_case_boundary_value_partial_match(
    adapter: AGTAdapter,
) -> None:
    """A prefix of an SDN ID ('SDN') must NOT be blocked."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"recipient_id": "SDN", "customer_id": "CUST-001", "account_id": "ACC-001"},
        context={},
        agent_id="agent-boundary",
    )
    assert result.approved is True
    assert VIOLATION_CODE not in result.violations


def test_finra_ofac_sanctions_edge_case_boundary_value_case_sensitivity(
    adapter: AGTAdapter,
) -> None:
    """SDN match is case-sensitive; 'sdn-001' must not match 'SDN-001'."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"recipient_id": "sdn-001", "customer_id": "CUST-001", "account_id": "ACC-001"},
        context={},
        agent_id="agent-boundary",
    )
    assert VIOLATION_CODE not in result.violations


def test_finra_ofac_sanctions_edge_case_boundary_value_flagged_fixture(
    adapter: AGTAdapter, ofac_flagged_recipient: str
) -> None:
    """conftest ofac_flagged_recipient fixture (SDN-001) must trigger a hard block."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"recipient_id": ofac_flagged_recipient, "amount": 100, "customer_id": "CUST-001", "account_id": "ACC-001"},
        context={},
        agent_id="agent-boundary",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations


def test_finra_ofac_sanctions_does_not_apply_to_equity_trade(
    adapter: AGTAdapter, ofac_flagged_recipient: str
) -> None:
    """OFAC rule is scoped to payment action types; equity_trade must not be blocked."""
    result = adapter.evaluate(
        action_type="equity_trade",
        parameters={"recipient_id": ofac_flagged_recipient, "customer_id": "CUST-001", "account_id": "ACC-001"},
        context={},
        agent_id="agent-scoping",
    )
    assert VIOLATION_CODE not in result.violations


def test_finra_ofac_sanctions_recipient_in_context(adapter: AGTAdapter) -> None:
    """SDN recipient supplied via context (not parameters) must still be blocked."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"amount": 500, "customer_id": "CUST-001", "account_id": "ACC-001"},
        context={"recipient_id": "SDN-002"},
        agent_id="agent-ctx",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations
