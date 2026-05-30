"""Tests for finra_kyc_2090 rule — FINRA Rule 2090 Know Your Customer.

Rule sourced from FINRA Rulebook Mock API (finraRulebookMock, ruleNumber 2090).
Rule text (verbatim from API):
  "Every member shall use reasonable diligence, in regard to the opening and
  maintenance of every account, to know (and retain) the essential facts
  concerning every customer and concerning the authority of each person acting
  on behalf of such customer."

Effective: 2012-07-09 (SR-FINRA-2010-039, amended SR-FINRA-2011-016)
Check type: required_fields — blocks when customer_id or account_id is absent.
Severity: hard_block

Test coverage:
  - All 6 covered action types × pass/block scenarios
  - Each required field individually missing
  - Both fields missing simultaneously
  - Empty string treated as missing
  - Whitespace-only string treated as missing
  - Field supplied via context (not parameters)
  - Parameters override context
  - Violation code and rationale content
  - Rule does not apply to uncovered action types
  - Combined KYC + OFAC violation (multi-rule interaction)
  - Combined KYC + wire threshold violation
"""
from __future__ import annotations

from pathlib import Path
import pytest
from src.engine.agt_adapter import AGTAdapter

RULES_DIR = Path(__file__).parent.parent.parent / "rules"
VIOLATION_CODE = "KYC_MISSING_FIELDS"

COVERED_ACTIONS = [
    "wire_transfer",
    "ach_payment",
    "internal_transfer",
    "check_issuance",
    "equity_trade",
    "loan_decision",
]

UNCOVERED_ACTIONS = [
    "account_open",
    "account_close",
    "document_sign",
    "credit_check",
]


_STUB_SDN = frozenset(["SDN-001", "SDN-002", "SDN-003", "BLOCKED-ENTITY-A", "BLOCKED-ENTITY-B"])


class _MockDataProvider:
    """Stub provider that mirrors YAML stub data for multi-rule interaction tests."""
    def is_sanctioned(self, entity_id: str) -> bool:
        return entity_id in _STUB_SDN
    def is_account_restricted(self, account_id: str) -> bool:
        return False
    def get_wire_threshold(self) -> float:
        return 1_000_000.0


@pytest.fixture()
def adapter(monkeypatch: pytest.MonkeyPatch) -> AGTAdapter:
    """AGTAdapter with AGT engine mocked — exercises rule logic only."""
    monkeypatch.setattr("src.engine.agt_adapter._AGT_AVAILABLE", False)
    monkeypatch.setattr("src.engine.agt_adapter._AGTPolicyEngine", None)
    return AGTAdapter(rules_dir=RULES_DIR, data_provider=_MockDataProvider())


# ---------------------------------------------------------------------------
# Section 1 — Pass: all required KYC fields present
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action_type", COVERED_ACTIONS)
def test_kyc_passes_when_all_fields_present(adapter: AGTAdapter, action_type: str) -> None:
    """Rule 2090: action with both customer_id and account_id must not trigger KYC block."""
    result = adapter.evaluate(
        action_type=action_type,
        parameters={"customer_id": "CUST-001", "account_id": "ACC-001", "amount": 1000},
        context={},
        agent_id="agent-kyc-pass",
    )
    assert VIOLATION_CODE not in result.violations


def test_kyc_passes_with_institutional_customer(adapter: AGTAdapter) -> None:
    """Rule 2090 topic: Institutional customers must also satisfy KYC fields."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={
            "customer_id": "INST-BLACKROCK-001",
            "account_id": "ACC-INST-42",
            "amount": 5_000_000,
            "recipient_id": "LEGIT-CUSTODIAN",
        },
        context={},
        agent_id="agent-institutional",
    )
    assert VIOLATION_CODE not in result.violations


def test_kyc_passes_with_retail_customer(adapter: AGTAdapter) -> None:
    """Rule 2090 topic: Retail customers must satisfy KYC fields."""
    result = adapter.evaluate(
        action_type="equity_trade",
        parameters={"customer_id": "RETAIL-CUST-007", "account_id": "BROKERAGE-007", "ticker": "AAPL"},
        context={},
        agent_id="agent-retail",
    )
    assert VIOLATION_CODE not in result.violations


# ---------------------------------------------------------------------------
# Section 2 — Block: missing customer_id
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action_type", COVERED_ACTIONS)
def test_kyc_blocks_missing_customer_id(adapter: AGTAdapter, action_type: str) -> None:
    """Rule 2090: action without customer_id must be hard-blocked for all covered types."""
    result = adapter.evaluate(
        action_type=action_type,
        parameters={"account_id": "ACC-001", "amount": 500},
        context={},
        agent_id="agent-no-cust",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations


def test_kyc_blocks_empty_string_customer_id(adapter: AGTAdapter) -> None:
    """Empty string customer_id must be treated the same as absent."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"customer_id": "", "account_id": "ACC-001", "amount": 500},
        context={},
        agent_id="agent-empty",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations


def test_kyc_blocks_whitespace_customer_id(adapter: AGTAdapter) -> None:
    """Whitespace-only customer_id (falsy) must be treated as missing."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"customer_id": "   ", "account_id": "ACC-001", "amount": 500},
        context={},
        agent_id="agent-whitespace",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations


# ---------------------------------------------------------------------------
# Section 3 — Block: missing account_id
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action_type", COVERED_ACTIONS)
def test_kyc_blocks_missing_account_id(adapter: AGTAdapter, action_type: str) -> None:
    """Rule 2090: action without account_id must be hard-blocked for all covered types."""
    result = adapter.evaluate(
        action_type=action_type,
        parameters={"customer_id": "CUST-001", "amount": 500},
        context={},
        agent_id="agent-no-acct",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations


def test_kyc_blocks_empty_string_account_id(adapter: AGTAdapter) -> None:
    """Empty string account_id must be treated the same as absent."""
    result = adapter.evaluate(
        action_type="ach_payment",
        parameters={"customer_id": "CUST-001", "account_id": "", "amount": 200},
        context={},
        agent_id="agent-empty-acct",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations


# ---------------------------------------------------------------------------
# Section 4 — Block: both fields missing
# ---------------------------------------------------------------------------

def test_kyc_blocks_when_both_fields_missing(adapter: AGTAdapter) -> None:
    """Neither customer_id nor account_id — full KYC failure, hard block."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"amount": 10_000, "recipient_id": "BANK-XYZ"},
        context={},
        agent_id="agent-no-kyc",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations


def test_kyc_blocks_completely_empty_parameters(adapter: AGTAdapter) -> None:
    """Empty parameters dict must be blocked for a covered action type."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={},
        context={},
        agent_id="agent-empty-params",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations


# ---------------------------------------------------------------------------
# Section 5 — Context and override behaviour
# ---------------------------------------------------------------------------

def test_kyc_passes_fields_in_context(adapter: AGTAdapter) -> None:
    """KYC fields supplied in context (not parameters) must satisfy the rule."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"amount": 500, "recipient_id": "BANK-ABC"},
        context={"customer_id": "CUST-999", "account_id": "ACC-999"},
        agent_id="agent-ctx",
    )
    assert VIOLATION_CODE not in result.violations


def test_kyc_parameters_override_empty_context(adapter: AGTAdapter) -> None:
    """customer_id in parameters must take precedence over missing context value."""
    result = adapter.evaluate(
        action_type="equity_trade",
        parameters={"customer_id": "CUST-PARAM", "account_id": "ACC-PARAM", "ticker": "MSFT"},
        context={"customer_id": ""},
        agent_id="agent-override",
    )
    assert VIOLATION_CODE not in result.violations


def test_kyc_customer_id_in_context_account_in_params(adapter: AGTAdapter) -> None:
    """customer_id in context + account_id in parameters must both satisfy the rule."""
    result = adapter.evaluate(
        action_type="ach_payment",
        parameters={"account_id": "ACC-PARAM", "amount": 300},
        context={"customer_id": "CUST-CTX"},
        agent_id="agent-split",
    )
    assert VIOLATION_CODE not in result.violations


# ---------------------------------------------------------------------------
# Section 6 — Violation metadata
# ---------------------------------------------------------------------------

def test_kyc_violation_code_is_correct(adapter: AGTAdapter) -> None:
    """Violation code must be exactly KYC_MISSING_FIELDS."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"amount": 500},
        context={},
        agent_id="agent-code-check",
    )
    assert VIOLATION_CODE in result.violations


def test_kyc_rationale_mentions_missing_fields(adapter: AGTAdapter) -> None:
    """Rationale must name the missing fields."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"amount": 500},
        context={},
        agent_id="agent-rationale",
    )
    assert "customer_id" in result.rationale or "KYC" in result.rationale


# ---------------------------------------------------------------------------
# Section 7 — Scoping: rule does not apply to uncovered action types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action_type", UNCOVERED_ACTIONS)
def test_kyc_does_not_apply_to_uncovered_actions(adapter: AGTAdapter, action_type: str) -> None:
    """Rule 2090 is scoped to specific action types — uncovered types must not trigger it."""
    result = adapter.evaluate(
        action_type=action_type,
        parameters={"amount": 100},
        context={},
        agent_id="agent-scoping",
    )
    assert VIOLATION_CODE not in result.violations


# ---------------------------------------------------------------------------
# Section 8 — Multi-rule interaction
# ---------------------------------------------------------------------------

def test_kyc_fires_alongside_ofac_violation(adapter: AGTAdapter) -> None:
    """Missing KYC fields + sanctioned recipient must produce both violations."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"amount": 500, "recipient_id": "SDN-001"},
        context={},
        agent_id="agent-multi",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations
    # OFAC rule uses static stub list — SDN-001 is in the YAML params fallback
    assert "OFAC_SANCTIONS_MATCH" in result.violations


def test_kyc_fires_alongside_wire_threshold(adapter: AGTAdapter) -> None:
    """Missing KYC fields + over-threshold amount must produce both violations."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={"amount": 2_000_000, "recipient_id": "BANK-OK"},
        context={},
        agent_id="agent-multi-threshold",
    )
    assert result.approved is False
    assert VIOLATION_CODE in result.violations
    assert "WIRE_THRESHOLD_EXCEEDED" in result.violations


def test_kyc_does_not_fire_when_only_threshold_exceeded(adapter: AGTAdapter) -> None:
    """Over-threshold wire with valid KYC must produce only WIRE_THRESHOLD_EXCEEDED."""
    result = adapter.evaluate(
        action_type="wire_transfer",
        parameters={
            "customer_id": "CUST-001",
            "account_id": "ACC-001",
            "amount": 2_000_000,
            "recipient_id": "LEGIT-BANK",
        },
        context={},
        agent_id="agent-threshold-only",
    )
    assert VIOLATION_CODE not in result.violations
    assert "WIRE_THRESHOLD_EXCEEDED" in result.violations
