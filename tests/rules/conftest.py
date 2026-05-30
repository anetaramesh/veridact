"""Shared fixtures for per-rule test modules.

All fixtures produce plain dicts that mirror the ``parameters`` and ``context``
arguments accepted by :meth:`~src.engine.agt_adapter.AGTAdapter.evaluate`.
The AGT policy engine is mocked at the module boundary; these fixtures are
independent of the live engine.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Valid action fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sample_wire_transfer_action() -> dict:
    """A valid, below-threshold wire transfer to a clean recipient."""
    return {
        "action_type": "wire_transfer",
        "parameters": {
            "recipient_id": "LEGIT-BANK-001",
            "amount": 50_000, "customer_id": "CUST-001", "account_id": "ACC-ACTIVE-999",
            "currency": "USD",
        },
        "context": {
            "account_id": "ACC-ACTIVE-999",
            "agent_id": "agent-finra-test",
        },
    }


@pytest.fixture()
def sample_trade_order_action() -> dict:
    """A valid equity trade order (not subject to wire/OFAC rules)."""
    return {
        "action_type": "equity_trade",
        "parameters": {
            "ticker": "AAPL",
            "quantity": 100,
            "side": "buy",
            "limit_price": 175.00,
        },
        "context": {
            "account_id": "ACC-ACTIVE-999",
            "agent_id": "agent-finra-test",
        },
    }


@pytest.fixture()
def sample_loan_decision_action() -> dict:
    """A valid loan approval action (not subject to wire/OFAC/freeze rules)."""
    return {
        "action_type": "loan_decision",
        "parameters": {
            "applicant_id": "APPL-123",
            "amount": 25_000,
            "term_months": 36,
        },
        "context": {
            "account_id": "ACC-ACTIVE-999",
            "agent_id": "agent-finra-test",
        },
    }


# ---------------------------------------------------------------------------
# Invalid / boundary fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def ofac_flagged_recipient() -> str:
    """A recipient ID that appears on the stub OFAC SDN sanctions list."""
    return "SDN-001"


@pytest.fixture()
def over_threshold_amount() -> int:
    """An amount that exceeds the $1,000,000 autonomous-execution limit."""
    return 1_000_001
